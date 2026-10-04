"""Verify session identity, expiration, cookie boundaries, and logout."""

from time import time

import pytest
from itsdangerous import TimestampSigner

import main
from _auth_test_helpers import (
    CLIENT_ID,
    EMAIL,
    SUBJECT,
    challenge,
    forbid_pipeline,
    headers,
    login,
)


def test_login_and_me_return_identity_and_secure_session(browser) -> None:
    client, _, verified = browser
    response = login(browser)
    body = response.json()
    assert body["user"] == {
        "sub": SUBJECT,
        "email": EMAIL,
        "name": "Aqua Reader",
        "picture": "https://example.com/avatar.png",
    }
    assert body["can_query"] is True and body["csrf_token"]
    assert verified == [("google-id-token", CLIENT_ID)]
    session = next(
        c
        for c in response.headers.get_list("set-cookie")
        if c.startswith("__Host-aqua_session=")
    )
    assert all(
        v in session.lower() for v in ("secure", "httponly", "path=/", "samesite=lax")
    )
    assert "domain=" not in session.lower()
    me = client.get("/api/auth/me")
    assert me.status_code == 200 and me.json() == body
    assert "no-store" in me.headers["cache-control"]


@pytest.mark.parametrize("cookie", [None, "forged.session.value"])
def test_missing_or_forged_session_cannot_query(browser, monkeypatch, cookie) -> None:
    client, _, _ = browser
    called = forbid_pipeline(monkeypatch)
    if cookie:
        client.cookies.set("__Host-aqua_session", cookie, domain="aqua-ai.us", path="/")
    assert client.get("/api/auth/me").status_code == 401
    response = client.post(
        "/api/query", json={"question": "List customers"}, headers=headers("forged")
    )
    assert response.status_code == 401 and called == []


def test_expired_session_cannot_query(browser, monkeypatch) -> None:
    client, _, _ = browser
    body = login(browser).json()
    called = forbid_pipeline(monkeypatch)
    expired_at = int(time()) + main.app.state.settings.session_max_age_seconds + 2
    monkeypatch.setattr(TimestampSigner, "get_timestamp", lambda self: expired_at)
    assert client.get("/api/auth/me").status_code == 401
    response = client.post(
        "/api/query", json={"question": "q"}, headers=headers(body["csrf_token"])
    )
    assert response.status_code == 401 and called == []


def test_login_cookie_cannot_be_used_as_session(browser) -> None:
    client, _, _ = browser
    challenge(browser)
    client.cookies.set(
        "__Host-aqua_session",
        client.cookies.get("__Host-aqua_login"),
        domain="aqua-ai.us",
        path="/",
    )
    assert client.get("/api/auth/me").status_code == 401


def test_logout_requires_csrf_and_clears_session(browser) -> None:
    client, _, _ = browser
    body = login(browser).json()
    assert client.post("/api/auth/logout", headers=headers("forged")).status_code == 403
    assert client.get("/api/auth/me").status_code == 200
    response = client.post("/api/auth/logout", headers=headers(body["csrf_token"]))
    assert response.status_code == 204
    assert response.content == b""
    assert "__Host-aqua_session" not in client.cookies
    assert client.get("/api/auth/me").status_code == 401
