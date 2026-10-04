"""Verify browser-bound login challenges and rejected Google identities."""

from time import time

import pytest
from google.auth.exceptions import GoogleAuthError, TransportError
from itsdangerous import TimestampSigner

from auth import router
from _auth_test_helpers import CLIENT_ID, challenge, headers


def test_challenge_sets_secure_cookie_and_no_store(browser) -> None:
    client, _, _ = browser
    response = client.get("/api/auth/config")
    body = response.json()
    assert response.status_code == 200
    assert body["client_id"] == CLIENT_ID
    assert body["nonce"] and body["csrf_token"]
    assert "no-store" in response.headers["cache-control"]
    cookie = response.headers["set-cookie"].lower()
    assert "__host-aqua_login=" in cookie
    assert all(
        value in cookie for value in ("secure", "httponly", "path=/", "samesite=lax")
    )
    assert "domain=" not in cookie


@pytest.mark.parametrize("change", ["origin", "csrf", "missing_origin", "missing_csrf"])
def test_login_rejects_origin_or_csrf_before_verification(browser, change) -> None:
    client, _, verified = browser
    data = challenge(browser)
    request_headers = headers(data["csrf_token"])
    if change.startswith("missing_"):
        request_headers.pop("Origin" if change == "missing_origin" else "X-CSRF-Token")
    else:
        request_headers["Origin" if change == "origin" else "X-CSRF-Token"] = (
            "https://evil.example" if change == "origin" else "forged"
        )
    response = client.post(
        "/api/auth/google", json={"credential": "token"}, headers=request_headers
    )
    assert response.status_code == 403
    assert verified == []
    assert "__Host-aqua_session" not in client.cookies


@pytest.mark.parametrize("invalid", ["nonce", "email_verified", "sub"])
def test_invalid_google_claims_cannot_create_session(browser, invalid) -> None:
    client, claims, _ = browser
    data = challenge(browser)
    claims[invalid] = {"nonce": "wrong-nonce", "email_verified": False, "sub": ""}[
        invalid
    ]
    response = client.post(
        "/api/auth/google",
        json={"credential": "token"},
        headers=headers(data["csrf_token"]),
    )
    assert response.status_code == 401
    assert "__Host-aqua_session" not in client.cookies


@pytest.mark.parametrize("error_type", [ValueError, GoogleAuthError])
def test_invalid_google_token_does_not_expose_verifier_error(
    browser, monkeypatch, error_type
) -> None:
    client, _, _ = browser
    data = challenge(browser)

    def invalid(*args):
        raise error_type("private verifier diagnostic")

    monkeypatch.setattr(router, "verify_google_token", invalid)
    response = client.post(
        "/api/auth/google",
        json={"credential": "bad"},
        headers=headers(data["csrf_token"]),
    )
    assert response.status_code == 401
    assert "private verifier diagnostic" not in response.text


def test_google_verification_outage_is_retryable_without_a_session(
    browser, monkeypatch
) -> None:
    client, _, _ = browser
    data = challenge(browser)

    def unavailable(*args):
        raise TransportError("private connection address")

    monkeypatch.setattr(router, "verify_google_token", unavailable)
    response = client.post(
        "/api/auth/google",
        json={"credential": "token"},
        headers=headers(data["csrf_token"]),
    )
    assert response.status_code == 503
    assert "private connection address" not in response.text
    assert "__Host-aqua_session" not in client.cookies


def test_login_challenge_cannot_be_reused(browser) -> None:
    client, _, _ = browser
    data = challenge(browser)
    for expected in (200, 403):
        response = client.post(
            "/api/auth/google",
            json={"credential": "token"},
            headers=headers(data["csrf_token"]),
        )
        assert response.status_code == expected


def test_expired_login_challenge_never_verifies_google(browser, monkeypatch) -> None:
    client, _, verified = browser
    data = challenge(browser)
    expired_at = int(time()) + 602
    monkeypatch.setattr(TimestampSigner, "get_timestamp", lambda self: expired_at)
    response = client.post(
        "/api/auth/google",
        json={"credential": "token"},
        headers=headers(data["csrf_token"]),
    )
    assert response.status_code == 403 and verified == []
