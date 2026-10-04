"""Browser-bound Google login and stateless session lifecycle under /api."""

import secrets
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from google.auth.exceptions import GoogleAuthError, TransportError
from pydantic import BaseModel, Field

from auth.google import verify_google_token
from auth.security import (
    UserSession,
    can_query,
    check_csrf,
    ensure_configured,
    get_settings,
    identity_from_claims,
    public_identity,
    require_user,
    tokens_match,
)
from auth.sessions import (
    LOGIN_MAX_AGE_SECONDS,
    challenge_cookie_name,
    clear_auth_cookie,
    read_payload,
    session_cookie_name,
    set_auth_cookie,
    sign_payload,
)
from nl2sql.config import Settings

router = APIRouter(prefix="/api/auth", tags=["authentication"])


class GoogleCredential(BaseModel):
    """Receive the GIS credential via JSON, never through a URL or log."""

    credential: str = Field(min_length=1, max_length=8192)


def _session_response(session: UserSession, settings: Settings) -> dict[str, Any]:
    return {
        "user": public_identity(session.user),
        "csrf_token": session.csrf_token,
        "can_query": can_query(session.user, settings),
    }


@router.get("/config")
def login_config(
    response: Response, settings: Settings = Depends(get_settings)
) -> dict[str, str]:
    """Issue a signed browser challenge for the next Google sign-in attempt."""
    ensure_configured(settings)
    challenge = {
        "nonce": secrets.token_urlsafe(32),
        "csrf_token": secrets.token_urlsafe(32),
    }
    set_auth_cookie(
        response,
        settings,
        challenge_cookie_name(settings),
        sign_payload(settings, challenge, "login"),
        LOGIN_MAX_AGE_SECONDS,
    )
    return {"client_id": settings.google_client_id, **challenge}


@router.post("/google")
def google_login(
    body: GoogleCredential,
    request: Request,
    response: Response,
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    """Verify identity and the browser challenge before creating an Aqua session."""
    ensure_configured(settings)
    challenge = read_payload(
        settings,
        request.cookies.get(challenge_cookie_name(settings)),
        "login",
        LOGIN_MAX_AGE_SECONDS,
    )
    if challenge is None:
        raise HTTPException(403, "Start a new sign-in attempt.")
    csrf_token, nonce = challenge.get("csrf_token"), challenge.get("nonce")
    if not isinstance(csrf_token, str) or not isinstance(nonce, str) or not nonce:
        raise HTTPException(403, "Start a new sign-in attempt.")
    check_csrf(request, csrf_token)
    try:
        claims = verify_google_token(body.credential, settings.google_client_id)
        claimed_nonce = claims.get("nonce")
        if not isinstance(claimed_nonce, str) or not tokens_match(claimed_nonce, nonce):
            raise ValueError("Invalid login nonce.")
        user = identity_from_claims(claims)
    except TransportError as exc:
        raise HTTPException(503, "Google sign-in is temporarily unavailable.") from exc
    except (ValueError, GoogleAuthError) as exc:
        raise HTTPException(401, "Google sign-in could not be verified.") from exc
    session = UserSession(user, secrets.token_urlsafe(32))
    set_auth_cookie(
        response,
        settings,
        session_cookie_name(settings),
        sign_payload(
            settings, {"user": user, "csrf_token": session.csrf_token}, "session"
        ),
        settings.session_max_age_seconds,
    )
    clear_auth_cookie(response, settings, challenge_cookie_name(settings))
    return _session_response(session, settings)


@router.get("/me")
def current_user(
    session: UserSession = Depends(require_user),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    """Restore browser identity and the current query permission after a reload."""
    return _session_response(session, settings)


@router.post("/logout", status_code=204)
def logout(
    response: Response,
    session: UserSession = Depends(require_user),
    settings: Settings = Depends(get_settings),
) -> None:
    """Clear this browser's cookies; copied stateless sessions expire separately."""
    clear_auth_cookie(response, settings, session_cookie_name(settings))
    clear_auth_cookie(response, settings, challenge_cookie_name(settings))
