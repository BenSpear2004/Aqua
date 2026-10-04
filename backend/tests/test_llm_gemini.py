"""Tests for the Gemini path in nl2sql/llm.py.

The SDK client is a stand-in that records each request, so these need
no API key and spend no quota.
"""

from dataclasses import replace
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

# Error-mapping tests check what Gemini failures look like, so they turn
# the Ollama fallback off; otherwise they would reach for a real server.
NO_FALLBACK = replace(SETTINGS, llm_fallback=False)


class FakeGenai:
    """Answers generate_content like the SDK; records each request."""

    def __init__(
        self, text: str | None = '{"sql": "SELECT 1"}', error=None, candidates=()
    ):
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
    reply = complete(
        "question",
        SETTINGS,
        system="rules",
        json_schema=SQL_REPLY_SCHEMA,
        client=client,
    )

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
    settings = Settings(
        llm_provider="gemini", gemini_api_key="k", gemini_model="gemma-4-31b-it"
    )
    complete(
        "question",
        settings,
        system="rules",
        json_schema=SQL_REPLY_SCHEMA,
        client=client,
    )

    (request,) = client.requests
    assert request["contents"] == "rules\n\nquestion"
    assert request["config"].system_instruction is None
    assert request["config"].response_json_schema is None


def test_generate_sql_works_through_gemini() -> None:
    client = FakeGenai(text='{"sql": "SELECT title FROM film"}')
    generation = generate_sql(
        "List films", "CREATE TABLE film (title text);", SETTINGS, client=client
    )
    assert generation.sql == "SELECT title FROM film"
    assert generation.model == "gemini-test-001"


def test_missing_key_is_an_error_before_any_request() -> None:
    client = FakeGenai()
    with pytest.raises(LLMError, match="GEMINI_API_KEY"):
        complete("q", Settings(llm_provider="gemini"), client=client)
    assert client.requests == []


def test_api_error_becomes_an_llm_error() -> None:
    error = errors.ClientError(
        429, {"error": {"code": 429, "message": "Resource exhausted"}}
    )
    with pytest.raises(LLMError, match="429"):
        complete("q", NO_FALLBACK, client=FakeGenai(error=error))


@pytest.mark.parametrize(
    "error", [httpx.ConnectError("no route"), httpx.ReadTimeout("slow")]
)
def test_network_failures_become_llm_errors(error: Exception) -> None:
    with pytest.raises(LLMError):
        complete("q", NO_FALLBACK, client=FakeGenai(error=error))


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


# ---- retries and the Ollama fallback ----


def ollama_answers(monkeypatch: pytest.MonkeyPatch) -> list:
    """Replace the Ollama call; returns what it was asked."""
    from nl2sql import llm
    from nl2sql.llm import Completion

    calls = []

    def fake_ollama(prompt, settings, system, json_schema, client):
        calls.append({"prompt": prompt, "system": system, "json_schema": json_schema})
        return Completion(text='{"sql": "SELECT 1"}', thinking="", model="qwen3:8b")

    monkeypatch.setattr(llm, "_complete_ollama", fake_ollama)
    return calls


def api_error(code: int) -> errors.APIError:
    return errors.APIError(
        code, {"error": {"code": code, "message": "boom", "status": "X"}}
    )


@pytest.mark.parametrize("code", [429, 500, 503])
def test_gemini_outages_fall_back_to_ollama(
    monkeypatch: pytest.MonkeyPatch, code: int
) -> None:
    calls = ollama_answers(monkeypatch)
    reply = complete(
        "q",
        SETTINGS,
        system="rules",
        json_schema=SQL_REPLY_SCHEMA,
        client=FakeGenai(error=api_error(code)),
    )
    assert reply.model == "qwen3:8b"  # the caller can see who answered
    # Ollama gets the system rules and schema even though Gemma could not.
    assert calls == [
        {"prompt": "q", "system": "rules", "json_schema": SQL_REPLY_SCHEMA}
    ]


def test_timeouts_fall_back_too(monkeypatch: pytest.MonkeyPatch) -> None:
    ollama_answers(monkeypatch)
    reply = complete("q", SETTINGS, client=FakeGenai(error=httpx.ReadTimeout("slow")))
    assert reply.model == "qwen3:8b"


@pytest.mark.parametrize("code", [400, 403, 404])
def test_configuration_mistakes_do_not_fall_back(
    monkeypatch: pytest.MonkeyPatch, code: int
) -> None:
    """A bad key or model name should fail loudly, not hide behind Ollama."""
    calls = ollama_answers(monkeypatch)
    with pytest.raises(LLMError, match=f"HTTP {code}"):
        complete("q", SETTINGS, client=FakeGenai(error=api_error(code)))
    assert calls == []


def test_fallback_can_be_switched_off(monkeypatch: pytest.MonkeyPatch) -> None:

    calls = ollama_answers(monkeypatch)
    with pytest.raises(LLMError) as caught:
        complete(
            "q",
            replace(SETTINGS, llm_fallback=False),
            client=FakeGenai(error=api_error(503)),
        )
    assert caught.value.transient is True and calls == []


def test_successful_gemini_never_touches_ollama(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = ollama_answers(monkeypatch)
    assert complete("q", SETTINGS, client=FakeGenai()).model == "gemini-test-001"
    assert calls == []


def test_retry_settings_cover_server_errors_but_not_quota() -> None:
    from nl2sql import llm

    assert llm.GEMINI_ATTEMPTS == 3
    assert 500 in llm.GEMINI_RETRY_CODES and 503 in llm.GEMINI_RETRY_CODES
    assert 429 not in llm.GEMINI_RETRY_CODES  # retrying a spent quota spends more


# ---- the Gemini model chain ----


class PerModelGenai:
    """Fails for the models in `down`, answers for the rest; records order."""

    def __init__(self, down: dict[str, Exception]) -> None:
        self.down = down
        self.asked: list[str] = []
        self.models = self

    def generate_content(self, model, contents, config):
        self.asked.append(model)
        if model in self.down:
            raise self.down[model]
        return SimpleNamespace(
            text="```sql\nSELECT 1\n```", candidates=[], model_version=model
        )


CHAIN = replace(
    SETTINGS,
    gemini_model="gemini-3.5-flash-lite",
    gemini_fallback_models=("gemma-4-26b-a4b-it",),
)


def test_the_main_model_answers_when_it_can(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = ollama_answers(monkeypatch)
    client = PerModelGenai({})
    assert complete("q", CHAIN, client=client).model == "gemini-3.5-flash-lite"
    assert client.asked == ["gemini-3.5-flash-lite"] and calls == []


@pytest.mark.parametrize("code", [429, 503])
def test_a_spent_or_down_model_hands_over_to_the_next(
    monkeypatch: pytest.MonkeyPatch, code: int
) -> None:
    calls = ollama_answers(monkeypatch)
    client = PerModelGenai({"gemini-3.5-flash-lite": api_error(code)})
    reply = complete("q", CHAIN, client=client)
    assert client.asked == ["gemini-3.5-flash-lite", "gemma-4-26b-a4b-it"]
    assert reply.model == "gemma-4-26b-a4b-it" and calls == []


def test_ollama_answers_only_when_every_gemini_model_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = ollama_answers(monkeypatch)
    client = PerModelGenai(
        {"gemini-3.5-flash-lite": api_error(429), "gemma-4-26b-a4b-it": api_error(500)}
    )
    assert complete("q", CHAIN, client=client).model == "qwen3:8b"
    assert len(calls) == 1


def test_a_configuration_mistake_stops_the_chain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = ollama_answers(monkeypatch)
    client = PerModelGenai({"gemini-3.5-flash-lite": api_error(404)})
    with pytest.raises(LLMError, match="HTTP 404"):
        complete("q", CHAIN, client=client)
    assert client.asked == ["gemini-3.5-flash-lite"] and calls == []


def test_without_fallback_only_the_main_model_is_tried() -> None:
    """The eval measures one model, so it turns fallback off."""
    client = PerModelGenai({"gemini-3.5-flash-lite": api_error(503)})
    with pytest.raises(LLMError):
        complete("q", replace(CHAIN, llm_fallback=False), client=client)
    assert client.asked == ["gemini-3.5-flash-lite"]


def test_gemma_in_the_chain_still_gets_the_rules_in_the_prompt() -> None:
    client = PerModelGenai({"gemini-3.5-flash-lite": api_error(429)})
    seen = {}
    original = client.generate_content

    def spy(model, contents, config):
        seen[model] = (contents, config.system_instruction)
        return original(model, contents, config)

    client.generate_content = spy
    complete(
        "question", CHAIN, system="rules", json_schema=SQL_REPLY_SCHEMA, client=client
    )
    assert seen["gemini-3.5-flash-lite"] == ("question", "rules")
    assert seen["gemma-4-26b-a4b-it"] == ("rules\n\nquestion", None)
