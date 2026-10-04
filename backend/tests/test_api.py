"""Tests for POST /api/query in main.py.

The pipeline is replaced with a stand-in, so these check only the HTTP
layer: status codes, the JSON body, and that outage details stay private.
"""

import pytest
from fastapi.testclient import TestClient

import main
from auth.security import UserSession, require_database_access
from nl2sql.db import DatabaseError
from nl2sql.llm import LLMError
from nl2sql.pipeline import Answer
from nl2sql.schema import Schema

client = TestClient(main.app)


SCHEMA = Schema(tables={})


@pytest.fixture(autouse=True)
def authenticated_query_contract():
    """Keep query-contract tests focused; test_auth checks the real auth gate."""
    main.app.dependency_overrides[require_database_access] = lambda: UserSession(
        {"sub": "query-test-user", "email": "query-test@gmail.com"}, "test-csrf"
    )
    yield
    main.app.dependency_overrides.pop(require_database_access, None)


def use_answer(monkeypatch: pytest.MonkeyPatch, result) -> list:
    """Replace the pipeline and the schema lookup; returns the questions asked."""
    asked = []

    def fake_answer_question(question, settings, schema, retriever=None):
        asked.append(question)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(main, "answer_question", fake_answer_question)
    monkeypatch.setattr(main, "get_schema", lambda settings: SCHEMA)
    return asked


def test_success(monkeypatch: pytest.MonkeyPatch) -> None:
    use_answer(
        monkeypatch,
        Answer(
            question="How many films?",
            sql="SELECT COUNT(*) FROM film LIMIT 1000",
            columns=["count"],
            rows=[(1000,)],
        ),
    )
    response = client.post("/api/query", json={"question": "How many films?"})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert body["sql"] == "SELECT COUNT(*) FROM film LIMIT 1000"
    assert body["tables"][0]["rows"] == [{"count": 1000}]


def test_rejected_sql_is_200_with_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    use_answer(
        monkeypatch,
        Answer(
            question="q",
            sql="DELETE FROM film",
            error="Only SELECT queries are allowed, got DELETE.",
            error_code="rejected",
        ),
    )
    response = client.post("/api/query", json={"question": "Delete all films"})

    assert response.status_code == 200
    assert response.json()["status"] == "error"
    assert response.json()["error"]["code"] == "rejected"


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (
            LLMError("Cannot connect to Ollama at http://100.64.0.1:11434/api/chat"),
            "model_unavailable",
        ),
        (
            DatabaseError("Could not connect to the database: host db.internal"),
            "database_unavailable",
        ),
    ],
)
def test_outages_are_503_without_internal_details(
    monkeypatch: pytest.MonkeyPatch, error, code
) -> None:
    use_answer(monkeypatch, error)
    response = client.post("/api/query", json={"question": "q"})

    assert response.status_code == 503
    body = response.json()
    assert body["error"]["code"] == code
    assert body["error"]["retryable"] is True
    assert "100.64.0.1" not in response.text and "db.internal" not in response.text


@pytest.mark.parametrize(
    "payload", [{"question": ""}, {"question": "   "}, {}, {"question": "x" * 2001}]
)
def test_bad_requests_never_reach_the_model(
    monkeypatch: pytest.MonkeyPatch, payload
) -> None:
    asked = use_answer(monkeypatch, AssertionError("should not be called"))
    response = client.post("/api/query", json=payload)

    assert response.status_code == 422
    assert asked == []


def test_question_whitespace_is_trimmed(monkeypatch: pytest.MonkeyPatch) -> None:
    asked = use_answer(
        monkeypatch, Answer(question="q", sql="SELECT 1", columns=["n"], rows=[(1,)])
    )
    client.post("/api/query", json={"question": "  How many films?  "})
    assert asked == ["How many films?"]


def test_schema_outage_is_a_503(monkeypatch: pytest.MonkeyPatch) -> None:
    """The schema is read on the first question; a database outage there
    is reported like any other, without the connection details."""

    def broken_schema(settings):
        raise DatabaseError("Could not read the schema: host db.internal")

    monkeypatch.setattr(main, "get_schema", broken_schema)
    response = client.post("/api/query", json={"question": "q"})

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "database_unavailable"
    assert "db.internal" not in response.text


def test_health_is_cheap_and_reports_configuration() -> None:
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert set(body) == {"status", "database_configured", "model", "retrieval"}


def test_starter_chat_routes_are_gone() -> None:
    assert client.post("/api/chat", json={"prompt": "hi"}).status_code == 404
