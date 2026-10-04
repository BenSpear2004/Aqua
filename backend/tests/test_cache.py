"""Tests for nl2sql/cache.py and its use in POST /api/query."""

import pytest
from fastapi.testclient import TestClient

import main
from auth.security import UserSession, require_database_access
from nl2sql.cache import AnswerCache, cache_key
from nl2sql.pipeline import Answer
from nl2sql.schema import Schema

OK = Answer(question="q", sql="SELECT 1", columns=["n"], rows=[(1,)])
FAILED = Answer(question="q", sql="SELECT nope", error="no", error_code="query_failed")


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_key_ignores_case_spacing_and_trailing_punctuation() -> None:
    assert cache_key("What are the  top films?", "gemini") == cache_key(
        "what are the top films", "gemini"
    )
    assert cache_key("top films", "gemini") != cache_key("top films", "ollama")


def test_successful_answers_are_reused_until_they_expire() -> None:
    clock = Clock()
    cache = AnswerCache(600, clock=clock)
    cache.put("k", OK)
    clock.now = 599
    assert cache.get("k") is OK
    clock.now = 601
    assert cache.get("k") is None


def test_failures_are_never_cached() -> None:
    cache = AnswerCache(600)
    cache.put("k", FAILED)
    assert cache.get("k") is None


def test_zero_seconds_turns_the_cache_off() -> None:
    cache = AnswerCache(0)
    cache.put("k", OK)
    assert cache.get("k") is None and not cache.enabled


def test_oldest_entries_are_dropped_beyond_the_limit() -> None:
    cache = AnswerCache(600, max_entries=2)
    for key in ("a", "b", "c"):
        cache.put(key, OK)
    assert cache.get("a") is None
    assert cache.get("b") is OK and cache.get("c") is OK


@pytest.fixture
def api(monkeypatch: pytest.MonkeyPatch):
    """The API with a real cache, a stand-in pipeline and a signed-in user."""
    asked = []

    def fake_answer_question(question, settings, schema, retriever=None):
        asked.append((question, settings.llm_provider))
        return Answer(question=question, sql="SELECT 1", columns=["n"], rows=[(1,)])

    monkeypatch.setattr(main, "ANSWER_CACHE", AnswerCache(600))
    monkeypatch.setattr(main, "answer_question", fake_answer_question)
    monkeypatch.setattr(main, "get_schema", lambda settings: Schema(tables={}))
    main.app.dependency_overrides[require_database_access] = lambda: UserSession(
        {"sub": "cache-test", "email": "cache-test@gmail.com"}, "csrf"
    )
    yield TestClient(main.app), asked
    main.app.dependency_overrides.pop(require_database_access, None)


def test_the_same_question_is_answered_once(api) -> None:
    client, asked = api
    first = client.post("/api/query", json={"question": "Top films?"})
    second = client.post("/api/query", json={"question": "top films"})
    assert first.json() == second.json()
    assert len(asked) == 1


def test_a_different_model_is_asked_separately(
    api, monkeypatch: pytest.MonkeyPatch
) -> None:
    from nl2sql.config import Settings

    monkeypatch.setattr(main, "SETTINGS", Settings(gemini_api_key="k"))
    client, asked = api
    client.post("/api/query", json={"question": "top films", "model": "ollama"})
    client.post("/api/query", json={"question": "top films", "model": "gemini"})
    assert [provider for _, provider in asked] == ["ollama", "gemini"]
