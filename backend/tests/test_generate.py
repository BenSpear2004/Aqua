"""Tests for nl2sql/generate.py.

No test here reaches a model. generate_sql gets an httpx client whose
network is replaced by a function returning a canned Ollama reply, so
these check what we control: the prompt, the request, and how the SQL is
pulled out of the reply. Whether the model writes good SQL is measured
separately, by running real questions against the database.
"""

import json

import httpx
import pytest

from nl2sql.config import Settings
from nl2sql.generate import (
    SQL_REPLY_SCHEMA,
    SYSTEM_INSTRUCTION,
    Attempt,
    Example,
    build_prompt,
    extract_sql,
    generate_sql,
)
from nl2sql.llm import LLMError

SETTINGS = Settings(ollama_base_url="http://ollama.test")
SCHEMA = "CREATE TABLE film (film_id INT, title VARCHAR(128));"


def mock_client(content: str = '{"sql": "SELECT 1"}', thinking: str = "", status: int = 200):
    """Return (client, requests) for a fake Ollama that replies with `content`."""
    requests: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        reply = {"model": "test-model", "message": {"content": content, "thinking": thinking}}
        return httpx.Response(status, json=reply)

    return httpx.Client(transport=httpx.MockTransport(handler)), requests


# ---- build_prompt ----


def test_prompt_has_schema_then_question() -> None:
    prompt = build_prompt("How many films?", SCHEMA)
    assert SCHEMA in prompt
    assert prompt.index(SCHEMA) < prompt.index("How many films?")
    assert prompt.endswith("Question: How many films?")


# ---- system instruction ----


def test_instruction_targets_postgres_and_case_insensitive_matching() -> None:
    """Both rules fixed wrong answers on the real database: without the
    ILIKE rule, questions like "actors named Nick" returned no rows
    because Pagila stores names in capitals."""
    assert "PostgreSQL" in SYSTEM_INSTRUCTION
    assert "MySQL" not in SYSTEM_INSTRUCTION
    assert "ILIKE" in SYSTEM_INSTRUCTION


def test_enum_columns_are_compared_with_equals() -> None:
    """ILIKE on an enum column is a Postgres error. In the first baseline
    run, "films rated PG-13" failed that way and needed the retry."""
    assert "ENUM" in SYSTEM_INSTRUCTION
    assert "rating = 'PG-13'" in SYSTEM_INSTRUCTION


# ---- extract_sql ----


@pytest.mark.parametrize(
    ("reply", "expected"),
    [
        ('{"sql": "SELECT 1"}', "SELECT 1"),
        ('{"sql": "  SELECT 1;  "}', "SELECT 1;"),
        ('{\n  "sql": "SELECT title\\nFROM film"\n}', "SELECT title\nFROM film"),
        ("```sql\nSELECT 1\n```", "SELECT 1"),
        ("Here:\n```\nSELECT 2\n```\nDone", "SELECT 2"),
        ("  SELECT 3  ", "SELECT 3"),
    ],
)
def test_extract_sql(reply: str, expected: str) -> None:
    assert extract_sql(reply) == expected


@pytest.mark.parametrize("reply", ['{"other": 1}', '{"sql": 5}', '["SELECT 1"]'])
def test_json_without_sql_string_falls_back_to_raw_text(reply: str) -> None:
    """Valid JSON of the wrong shape is passed on as-is for the validator to reject."""
    assert extract_sql(reply) == reply


# ---- generate_sql ----


def test_sends_question_schema_rules_and_reply_schema() -> None:
    client, requests = mock_client()
    generate_sql("How many films?", SCHEMA, SETTINGS, client=client)

    (body,) = requests
    system, user = body["messages"]
    assert system == {"role": "system", "content": SYSTEM_INSTRUCTION}
    assert "How many films?" in user["content"]
    assert SCHEMA in user["content"]
    assert body["format"] == SQL_REPLY_SCHEMA


def test_returns_sql_reasoning_and_model() -> None:
    client, _ = mock_client('{"sql": "SELECT COUNT(*) FROM film"}', thinking="Count rows.")
    result = generate_sql("How many films?", SCHEMA, SETTINGS, client=client)
    assert result.sql == "SELECT COUNT(*) FROM film"
    assert result.thinking == "Count rows."
    assert result.model == "test-model"


def test_question_whitespace_is_trimmed() -> None:
    client, requests = mock_client()
    generate_sql("   How many films?  \n", SCHEMA, SETTINGS, client=client)
    assert requests[0]["messages"][1]["content"].endswith("Question: How many films?")


@pytest.mark.parametrize("question", ["", "   ", "\n"])
def test_empty_question_is_rejected_without_calling_model(question: str) -> None:
    client, requests = mock_client()
    with pytest.raises(ValueError, match="empty"):
        generate_sql(question, SCHEMA, SETTINGS, client=client)
    assert requests == []  # no model call for a blank question


def test_model_failure_surfaces_as_llm_error() -> None:
    """generate_sql does not catch LLMError; the caller decides what to do."""
    client, _ = mock_client(status=500)
    with pytest.raises(LLMError):
        generate_sql("q", SCHEMA, SETTINGS, client=client)


# ---- examples and retries ----


def test_examples_sit_between_schema_and_question() -> None:
    examples = [Example("How many actors?", "SELECT count(*) FROM actor")]
    prompt = build_prompt("How many films?", SCHEMA, examples)
    assert prompt.index(SCHEMA) < prompt.index("How many actors?") < prompt.index("Question: How many films?")
    assert "SQL: SELECT count(*) FROM actor" in prompt


def test_no_examples_means_no_examples_heading() -> None:
    assert "Examples" not in build_prompt("q", SCHEMA)


def test_previous_attempt_comes_last_with_its_error() -> None:
    previous = Attempt("SELECT nope FROM film", 'column "nope" does not exist')
    prompt = build_prompt("q", SCHEMA, previous=previous)
    assert prompt.endswith("Write a corrected query that answers the question.")
    assert prompt.index("Question: q") < prompt.index("SELECT nope FROM film")
    assert 'It failed: column "nope" does not exist' in prompt


def test_examples_and_previous_attempt_reach_the_model() -> None:
    client, requests = mock_client()
    generate_sql(
        "How many films?",
        SCHEMA,
        SETTINGS,
        client=client,
        examples=[Example("How many actors?", "SELECT count(*) FROM actor")],
        previous=Attempt("SELEC 1", "could not be parsed"),
    )
    sent = requests[0]["messages"][-1]["content"]
    assert "How many actors?" in sent and "could not be parsed" in sent


def test_instruction_asks_for_named_columns_and_aliases() -> None:
    assert "never use SELECT *" in SYSTEM_INSTRUCTION
    assert "snake_case alias" in SYSTEM_INSTRUCTION
