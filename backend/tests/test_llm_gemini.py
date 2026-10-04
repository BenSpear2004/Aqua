"""Tests for the Gemini path in nl2sql/llm.py.

The SDK client is a stand-in that records each request, so these need
no API key and spend no quota.
"""

from types import SimpleNamespace

import httpx
import pytest
from google.genai import errors

from nl2sql.config import Settings
from nl2sql.generate import SQL_REPLY_SCHEMA, generate_sql
from nl2sql.llm import SEED, LLMError, complete

SETTINGS = Settings(
    llm_provider="gemini", gemini_api_key="test-key", gemini_model="gemini-test"
)


class FakeGenai:
    """Answers generate_content like the SDK; records each request."""

    def __init__(self, text: str | None = '{"sql": "SELECT 1"}', error=None, candidates=()):
        self.text = text
        self.error = error
        self.candidates = list(candidates)
        self.requests: list[dict] = []
        self.models = self

    def generate_content(self, model, contents, config):
        self.requests.append({"model": model, "contents": contents, "config": config})
        if self.error is not None:
            raise self.error
        return SimpleNamespace(
            text=self.text, candidates=self.candidates, model_version="gemini-test-001"
        )


def test_gemini_gets_system_instruction_schema_and_seed() -> None:
    client = FakeGenai()
    reply = complete("question", SETTINGS, system="rules", json_schema=SQL_REPLY_SCHEMA, client=client)

    (request,) = client.requests
    assert request["model"] == "gemini-test"
    assert request["contents"] == "question"
    config = request["config"]
    assert config.system_instruction == "rules"
    assert config.response_mime_type == "application/json"
    assert config.response_json_schema == SQL_REPLY_SCHEMA
    assert config.seed == SEED
    assert reply.text == '{"sql": "SELECT 1"}'
    assert reply.model == "gemini-test-001"
    assert reply.thinking == ""


def test_gemma_gets_rules_in_the_prompt_and_no_schema() -> None:
    """Gemma on the API refuses system instructions and JSON mode."""
    client = FakeGenai(text="```sql\nSELECT 1\n```")
    settings = Settings(llm_provider="gemini", gemini_api_key="k", gemini_model="gemma-4-31b-it")
    complete("question", settings, system="rules", json_schema=SQL_REPLY_SCHEMA, client=client)

    (request,) = client.requests
    assert request["contents"] == "rules\n\nquestion"
    assert request["config"].system_instruction is None
    assert request["config"].response_json_schema is None


def test_generate_sql_works_through_gemini() -> None:
    client = FakeGenai(text='{"sql": "SELECT title FROM film"}')
    generation = generate_sql("List films", "CREATE TABLE film (title text);", SETTINGS, client=client)
    assert generation.sql == "SELECT title FROM film"
    assert generation.model == "gemini-test-001"


def test_missing_key_is_an_error_before_any_request() -> None:
    client = FakeGenai()
    with pytest.raises(LLMError, match="GEMINI_API_KEY"):
        complete("q", Settings(llm_provider="gemini"), client=client)
    assert client.requests == []


def test_api_error_becomes_an_llm_error() -> None:
    error = errors.ClientError(429, {"error": {"code": 429, "message": "Resource exhausted"}})
    with pytest.raises(LLMError, match="429"):
        complete("q", SETTINGS, client=FakeGenai(error=error))


@pytest.mark.parametrize(
    "error", [httpx.ConnectError("no route"), httpx.ReadTimeout("slow")]
)
def test_network_failures_become_llm_errors(error: Exception) -> None:
    with pytest.raises(LLMError):
        complete("q", SETTINGS, client=FakeGenai(error=error))


def test_empty_reply_reports_why() -> None:
    client = FakeGenai(text=None, candidates=[SimpleNamespace(finish_reason="SAFETY")])
    with pytest.raises(LLMError, match="SAFETY"):
        complete("q", SETTINGS, client=client)


def test_ollama_is_still_the_default() -> None:
    assert Settings().llm_provider == "ollama"


def test_automatic_function_calling_is_off() -> None:
    """No tools are sent, so it only added a warning to every call."""
    client = FakeGenai()
    complete("q", SETTINGS, client=client)
    assert client.requests[0]["config"].automatic_function_calling.disable is True
