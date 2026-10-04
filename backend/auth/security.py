"""Require both a verified session and explicit permission to query the database."""

import hmac
from dataclasses import dataclass
from typing import Any

from fastapi import Depends, HTTPException, Request

from auth.sessions import read_payload, session_cookie_name
from nl2sql.config import Settings


def get_settings(request: Request) -> Settings:
    """Keep authentication configuration on the app, where tests can replace it."""
    return request.app.state.settings


def ensure_configured(settings: Settings) -> None:
    """Keep health checks working while unconfigured authentication fails closed."""
    if not settings.google_client_id or len(settings.session_secret) < 32:
        raise HTTPException(503, "Google sign-in is not configured.")


def tokens_match(actual: str, expected: str) -> bool:
    """Compare even non-ASCII input without leaking the expected token."""
    return hmac.compare_digest(actual.encode("utf-8"), expected.encode("utf-8"))


def check_csrf(request: Request, expected: str) -> None:
    """Bind authenticated actions to the configured site and browser session."""
    settings = get_settings(request)
    if request.headers.get("origin") != settings.app_origin:
        raise HTTPException(403, "Request origin is not allowed.")
    actual = request.headers.get("x-csrf-token", "")
    if not actual or not expected or not tokens_match(actual, expected):
        raise HTTPException(403, "Invalid CSRF token.")


def identity_from_claims(claims: dict[str, Any]) -> dict[str, Any]:
    """Only verified identity claims belong in a signed session; never the JWT."""
    subject, email = claims.get("sub"), claims.get("email")
    if (
        not isinstance(subject, str)
        or not 1 <= len(subject) <= 255
        or not isinstance(email, str)
        or not 3 <= len(email) <= 320
        or "@" not in email
        or claims.get("email_verified") is not True
    ):
        raise ValueError("Google identity is incomplete or unverified.")
    identity: dict[str, Any] = {
        "sub": subject,
        "email": email.lower(),
        "email_verified": True,
    }
    for key, limit in (("name", 256), ("picture", 1024), ("hd", 253)):
        value = claims.get(key, "")
        identity[key] = value if isinstance(value, str) and len(value) <= limit else ""
    return identity


def can_query(identity: dict[str, Any], settings: Settings) -> bool:
    """Sign-in establishes identity; configuration grants database access."""
    if identity["sub"] in settings.auth_allowed_google_subs:
        return True
    email = identity["email"]
    # Google owns Gmail/Workspace email identity. For other email providers,
    # email_verified can outlive mailbox ownership: require an explicit sub.
    authoritative = email.rsplit("@", 1)[-1] == "gmail.com" or bool(identity["hd"])
    return authoritative and email in settings.auth_allowed_emails


def public_identity(identity: dict[str, Any]) -> dict[str, str]:
    """Expose the profile needed by the UI without internal authorization claims."""
    return {key: identity[key] for key in ("sub", "email", "name", "picture")}


@dataclass(frozen=True)
class UserSession:
    """Carry a validated identity and its CSRF token through dependencies."""

    user: dict[str, Any]
    csrf_token: str


def require_user(
    request: Request, settings: Settings = Depends(get_settings)
) -> UserSession:
    """Reject missing/invalid cookies before any database or model work."""
    ensure_configured(settings)
    payload = read_payload(
        settings,
        request.cookies.get(session_cookie_name(settings)),
        "session",
        settings.session_max_age_seconds,
    )
    if payload is None:
        raise HTTPException(401, "Sign in to continue.")
    try:
        claims = payload.get("user")
        if not isinstance(claims, dict):
            raise ValueError("Invalid session.")
        identity = identity_from_claims(claims)
        csrf_token = payload.get("csrf_token")
        if not isinstance(csrf_token, str) or not csrf_token:
            raise ValueError("Invalid session.")
    except ValueError as exc:
        raise HTTPException(401, "Sign in to continue.") from exc
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        check_csrf(request, csrf_token)
    return UserSession(identity, csrf_token)


def require_database_access(
    session: UserSession = Depends(require_user),
    settings: Settings = Depends(get_settings),
) -> UserSession:
    """Recheck the current allowlist on each query, including existing sessions."""
    if not can_query(session.user, settings):
        raise HTTPException(403, "This account cannot query the database.")
    return session
