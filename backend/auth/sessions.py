"""Sign short-lived cookies without keeping a server-side account database."""

from typing import Any

from fastapi import Response
from itsdangerous import BadData, URLSafeTimedSerializer

from nl2sql.config import Settings

LOGIN_MAX_AGE_SECONDS = 600


def challenge_cookie_name(settings: Settings) -> str:
    """Use a host-bound cookie on HTTPS and a separate name for local HTTP."""
    return _cookie_name(settings, "login")


def session_cookie_name(settings: Settings) -> str:
    """Prevent production cookies from being shared with unrelated subdomains."""
    return _cookie_name(settings, "session")


def _cookie_name(settings: Settings, kind: str) -> str:
    prefix = "__Host-" if settings.app_origin.startswith("https://") else ""
    return f"{prefix}aqua_{kind}"


def sign_payload(settings: Settings, payload: dict[str, Any], purpose: str) -> str:
    """Separate challenge and session signatures so neither replaces the other."""
    return URLSafeTimedSerializer(
        settings.session_secret, salt=f"aqua-{purpose}-v1"
    ).dumps(payload)


def read_payload(
    settings: Settings, value: str | None, purpose: str, max_age: int
) -> dict[str, Any] | None:
    """Treat missing, modified and expired cookies as unauthenticated."""
    if not value or len(value) > 8192:
        return None
    try:
        payload = URLSafeTimedSerializer(
            settings.session_secret, salt=f"aqua-{purpose}-v1"
        ).loads(value, max_age=max_age)
    except BadData:
        return None
    return payload if isinstance(payload, dict) else None


def set_auth_cookie(
    response: Response, settings: Settings, name: str, value: str, max_age: int
) -> None:
    """Cookies remain inaccessible to JavaScript and confined to this host."""
    response.set_cookie(
        name,
        value,
        max_age=max_age,
        path="/",
        secure=settings.app_origin.startswith("https://"),
        httponly=True,
        samesite="lax",
    )


def clear_auth_cookie(response: Response, settings: Settings, name: str) -> None:
    """Match the original cookie attributes when removing it."""
    response.delete_cookie(
        name,
        path="/",
        secure=settings.app_origin.startswith("https://"),
        httponly=True,
        samesite="lax",
    )
