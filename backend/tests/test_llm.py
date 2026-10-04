"""Tests for nl2sql/llm.py.

None of these reach Ollama. Each test plugs an httpx.MockTransport into a
real httpx.Client: the request code runs for real, but the "network"
is a function that records the request and returns a canned response.
"""

import json

import httpx
import pytest

from nl2sql.config import Settings
from nl2sql.llm import (
    NON_THINKING_OPTIONS,
    SEED,
    THINKING_OPTIONS,
    LLMError,
    complete,
)

SETTINGS = Settings(ollama_base_url="http://ollama.test", ollama_model="test-model")


def mock_client(reply: dict | None = None, status: int = 200, error: Exception | None = None):
    """Return (client, requests). `requests` fills up as the client is used."""
    requests: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append({"url": str(request.url), "body": json.loads(request.content)})
        if error is not None:
            raise error
        return httpx.Response(status, json=reply if reply is not None else {})

    return httpx.Client(transport=httpx.MockTransport(handler)), requests


def ollama_reply(content: str, thinking: str = "") -> dict:
    """The shape of a non-streaming /api/chat response."""
    return {
        "model": "test-model",
        "message": {"role": "assistant", "content": content, "thinking": thinking},
        "done_reason": "stop",
    }


# ---- what gets sent ----


def test_request_goes_to_chat_endpoint_with_model() -> None:
    client, requests = mock_client(ollama_reply("ok"))
    complete("q", SETTINGS, client=client)

    (request,) = requests
    assert request["url"] == "http://ollama.test/api/chat"
    assert request["body"]["model"] == "test-model"
    assert request["body"]["stream"] is False


def test_system_message_comes_first() -> None:
    client, requests = mock_client(ollama_reply("ok"))
    complete("the question", SETTINGS, system="the rules", client=client)

    messages = requests[0]["body"]["messages"]
    assert messages == [
        {"role": "system", "content": "the rules"},
        {"role": "user", "content": "the question"},
    ]


def test_no_system_message_when_not_given() -> None:
    client, requests = mock_client(ollama_reply("ok"))
    complete("q", SETTINGS, client=client)
    assert [m["role"] for m in requests[0]["body"]["messages"]] == ["user"]


def test_thinking_mode_uses_thinking_options() -> None:
    client, requests = mock_client(ollama_reply("ok"))
    complete("q", Settings(ollama_think=True), client=client)

    body = requests[0]["body"]
    assert body["think"] is True
    assert body["options"]["temperature"] == THINKING_OPTIONS["temperature"]
    assert body["options"]["seed"] == SEED


def test_non_thinking_mode_uses_non_thinking_options() -> None:
    client, requests = mock_client(ollama_reply("ok"))
    complete("q", Settings(ollama_think=False), client=client)

    body = requests[0]["body"]
    assert body["think"] is False
    assert body["options"]["temperature"] == NON_THINKING_OPTIONS["temperature"]


def test_json_schema_is_sent_as_format() -> None:
    schema = {"type": "object", "properties": {"sql": {"type": "string"}}}
    client, requests = mock_client(ollama_reply('{"sql": "SELECT 1"}'))
    complete("q", SETTINGS, json_schema=schema, client=client)
    assert requests[0]["body"]["format"] == schema


def test_no_format_without_schema() -> None:
    client, requests = mock_client(ollama_reply("ok"))
    complete("q", SETTINGS, client=client)
    assert "format" not in requests[0]["body"]


# ---- what comes back ----


def test_answer_and_reasoning_are_kept_separate() -> None:
    client, _ = mock_client(ollama_reply("  SELECT 1  ", thinking=" I should count. "))
    result = complete("q", SETTINGS, client=client)
    assert result.text == "SELECT 1"
    assert result.thinking == "I should count."
    assert result.model == "test-model"


def test_missing_thinking_becomes_empty_string() -> None:
    client, _ = mock_client({"model": "m", "message": {"content": "SELECT 1"}})
    assert complete("q", SETTINGS, client=client).thinking == ""


@pytest.mark.parametrize("reply", [ollama_reply(""), ollama_reply("   "), {"done_reason": "length"}])
def test_empty_answer_is_an_error(reply: dict) -> None:
    client, _ = mock_client(reply)
    with pytest.raises(LLMError, match="no answer"):
        complete("q", SETTINGS, client=client)


# ---- failures ----


def test_http_error_includes_ollamas_explanation() -> None:
    client, _ = mock_client({"error": "model 'nope' not found"}, status=404)
    with pytest.raises(LLMError, match="404.*not found"):
        complete("q", SETTINGS, client=client)


def test_connection_failure_is_an_llm_error() -> None:
    client, _ = mock_client(error=httpx.ConnectError("refused"))
    with pytest.raises(LLMError, match="Cannot connect"):
        complete("q", SETTINGS, client=client)


def test_timeout_is_an_llm_error() -> None:
    client, _ = mock_client(error=httpx.ReadTimeout("slow"))
    with pytest.raises(LLMError, match="too long"):
        complete("q", SETTINGS, client=client)


def test_non_json_reply_is_an_llm_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>not json</html>")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(LLMError, match="not JSON"):
        complete("q", SETTINGS, client=client)


def test_our_own_bugs_are_not_hidden() -> None:
    """Only network and HTTP problems become LLMError; real bugs surface as themselves."""
    client, _ = mock_client(error=AttributeError("a real bug"))
    with pytest.raises(AttributeError):
        complete("q", SETTINGS, client=client)
