"""Verify database authorization is separate from Google sign-in."""

from dataclasses import replace

import pytest

import main
from nl2sql.config import Settings
from nl2sql.pipeline import Answer
from nl2sql.schema import Schema
from _auth_test_helpers import EMAIL, ORIGIN, SUBJECT, forbid_pipeline, headers, login


@pytest.mark.parametrize(
    ("email", "hosted_domain", "allow_email", "allow_sub", "allowed"),
    [
        (EMAIL, None, True, False, True),
        ("reader@company.example", "company.example", True, False, True),
        ("reader@company.example", None, True, False, False),
        ("reader@company.example", None, False, True, True),
        (EMAIL, None, False, False, False),
    ],
)
def test_query_allowlist_requires_authoritative_email_or_explicit_subject(
    browser,
    monkeypatch,
    email,
    hosted_domain,
    allow_email,
    allow_sub,
    allowed,
) -> None:
    client, claims, _ = browser
    claims["email"] = email
    if hosted_domain:
        claims["hd"] = hosted_domain
    monkeypatch.setattr(
        main.app.state,
        "settings",
        replace(
            main.app.state.settings,
            auth_allowed_emails=frozenset({email}) if allow_email else frozenset(),
            auth_allowed_google_subs=frozenset({SUBJECT}) if allow_sub else frozenset(),
        ),
    )
    body = login(browser).json()
    assert body["can_query"] is allowed
    called = []

    def answer(question, settings, schema, retriever=None):
        called.append(question)
        return Answer(question=question, sql="SELECT 1", columns=["n"], rows=[(1,)])

    monkeypatch.setattr(main, "get_schema", lambda settings: Schema(tables={}))
    monkeypatch.setattr(main, "answer_question", answer)
    response = client.post(
        "/api/query",
        json={"question": "How many?"},
        headers=headers(body["csrf_token"]),
    )
    assert response.status_code == (200 if allowed else 403)
    assert called == (["How many?"] if allowed else [])


def test_logged_in_query_requires_csrf(browser, monkeypatch) -> None:
    client, _, _ = browser
    body = login(browser).json()
    called = forbid_pipeline(monkeypatch)
    for request_headers in (
        {"Origin": ORIGIN},
        headers("forged"),
        {**headers(body["csrf_token"]), "Origin": "https://evil.example"},
    ):
        response = client.post(
            "/api/query", json={"question": "q"}, headers=request_headers
        )
        assert response.status_code == 403
    assert called == []


def test_allowlist_revocation_applies_to_existing_session(browser, monkeypatch) -> None:
    client, _, _ = browser
    body = login(browser).json()
    assert body["can_query"] is True
    called = forbid_pipeline(monkeypatch)
    monkeypatch.setattr(
        main.app.state,
        "settings",
        replace(
            main.app.state.settings,
            auth_allowed_emails=frozenset(),
        ),
    )
    response = client.get("/api/auth/me")
    assert response.status_code == 200
    assert response.json()["can_query"] is False
    response = client.post(
        "/api/query", json={"question": "q"}, headers=headers(body["csrf_token"])
    )
    assert response.status_code == 403 and called == []


def test_auth_unconfigured_fails_closed_but_health_is_public(
    browser, monkeypatch
) -> None:
    client, _, _ = browser
    monkeypatch.setattr(main.app.state, "settings", Settings())
    called = forbid_pipeline(monkeypatch)
    assert client.get("/api/auth/config").status_code == 503
    assert (
        client.post(
            "/api/query", json={"question": "q"}, headers=headers("forged")
        ).status_code
        == 503
    )
    assert client.get("/api/health").status_code == 200
    assert called == []
