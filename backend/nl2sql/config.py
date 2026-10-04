"""Read settings from environment variables into one typed, read-only object.

Every other module receives a Settings object as an argument instead of
calling os.getenv itself, so the variable names and defaults live in one
place and tests can build Settings by hand without touching the
environment.

Variable names match docker-compose.yml and main.py. Defaults let the
backend start with no configuration at all; only values that are present
but wrong raise an error.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

from nl2sql.auth_config import normalize_app_origin

DEFAULT_OLLAMA_BASE_URL = "http://127.0.0.1:11434"
DEFAULT_OLLAMA_MODEL = "qwen3:8b"
DEFAULT_GEMINI_MODEL = "gemma-4-31b-it"
DEFAULT_GEMINI_EMBED_MODEL = "gemini-embedding-2"
DEFAULT_APP_ORIGIN = "https://aqua-ai.us"
DEFAULT_SESSION_MAX_AGE_SECONDS = 3600

# The repo-root .env, two folders up from this file (backend/nl2sql/).
# Inside the Docker image this path does not exist, which is fine:
# docker-compose passes the same values in as environment variables.
ENV_FILE = Path(__file__).resolve().parents[2] / ".env"

_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}
_GOOGLE_CLIENT_ID = re.compile(r"[A-Za-z0-9_-]+\.apps\.googleusercontent\.com")


class ConfigError(RuntimeError):
    """Raised when an environment variable is set to an unusable value."""


@dataclass(frozen=True)
class Settings:
    """Everything the pipeline needs to know about its environment.

    Frozen, so no module can change a setting another module relies on.
    """

    ollama_base_url: str = DEFAULT_OLLAMA_BASE_URL
    ollama_model: str = DEFAULT_OLLAMA_MODEL
    # Whether the model reasons before answering. Slower but more
    # accurate in our tests; qwen3:8b supports turning it off.
    ollama_think: bool = True
    # The read-only nl2sql_reader connection. Hidden when printed
    # because database URLs usually contain the password.
    database_url: str = field(default="", repr=False)
    # The nl2sql_indexer connection, used only by the offline embedding
    # indexer (retrieval/store.py), never by the web app.
    indexer_database_url: str = field(default="", repr=False)
    # Gemini API: embeddings for retrieval, and the free Gemma backup.
    gemini_api_key: str = field(default="", repr=False)
    gemini_model: str = DEFAULT_GEMINI_MODEL
    gemini_embed_model: str = DEFAULT_GEMINI_EMBED_MODEL
    # Retrieve relevant tables and examples per question (Phase 4). Off
    # until the indexer has run and the eval shows it helps.
    retrieval: bool = False
    # Google sign-in uses an ID token, not the Gemini model API key.
    google_client_id: str = ""
    session_secret: str = field(default="", repr=False)
    app_origin: str = DEFAULT_APP_ORIGIN
    session_max_age_seconds: int = DEFAULT_SESSION_MAX_AGE_SECONDS
    # Empty allowlists grant no access. Google subjects are case-sensitive;
    # email entries are normalized to lowercase when loading configuration.
    auth_allowed_google_subs: frozenset[str] = field(default_factory=frozenset)
    auth_allowed_emails: frozenset[str] = field(default_factory=frozenset)


def _flag(name: str, value: str) -> bool:
    """Parse an on/off environment variable, rejecting anything unclear."""
    lowered = value.strip().lower()
    if lowered in _TRUE:
        return True
    if lowered in _FALSE:
        return False
    raise ConfigError(f"{name} must be true or false, got {value!r}.")


def _comma_set(value: str, *, lowercase: bool = False) -> frozenset[str]:
    """Trim comma-separated allowlist entries and discard empty entries."""
    entries = (entry.strip() for entry in value.split(","))
    return frozenset(
        entry.lower() if lowercase else entry for entry in entries if entry
    )


def settings_from(environ: Mapping[str, str]) -> Settings:
    """Build Settings from any mapping of variable names to values.

    Takes the mapping as an argument so tests can pass a plain dict
    instead of changing real environment variables. Unset or blank
    variables fall back to the defaults above.
    """

    def get(name: str) -> str:
        return environ.get(name, "").strip()

    base_url = get("OLLAMA_BASE_URL") or DEFAULT_OLLAMA_BASE_URL
    if not base_url.startswith(("http://", "https://")):
        raise ConfigError(
            f"OLLAMA_BASE_URL must start with http:// or https://, got {base_url!r}."
        )

    think = get("OLLAMA_THINK")
    retrieval = get("RETRIEVAL")
    google_client_id = get("GOOGLE_CLIENT_ID")
    if google_client_id and not _GOOGLE_CLIENT_ID.fullmatch(google_client_id):
        raise ConfigError(
            "GOOGLE_CLIENT_ID must be a valid Google web application client ID."
        )
    session_secret = get("SESSION_SECRET")
    if session_secret and len(session_secret) < 32:
        raise ConfigError("SESSION_SECRET must contain at least 32 characters.")
    session_max_age = get("SESSION_MAX_AGE_SECONDS")
    try:
        session_max_age_seconds = (
            int(session_max_age) if session_max_age else DEFAULT_SESSION_MAX_AGE_SECONDS
        )
    except ValueError:
        raise ConfigError(
            "SESSION_MAX_AGE_SECONDS must be an integer between 300 and 86400."
        ) from None
    if not 300 <= session_max_age_seconds <= 86400:
        raise ConfigError(
            "SESSION_MAX_AGE_SECONDS must be an integer between 300 and 86400."
        )
    try:
        app_origin = normalize_app_origin(get("APP_ORIGIN") or DEFAULT_APP_ORIGIN)
    except ValueError as exc:
        raise ConfigError(str(exc)) from None
    return Settings(
        ollama_base_url=base_url.rstrip("/"),
        ollama_model=get("OLLAMA_MODEL") or DEFAULT_OLLAMA_MODEL,
        ollama_think=_flag("OLLAMA_THINK", think) if think else True,
        database_url=get("DATABASE_URL"),
        indexer_database_url=get("INDEXER_DATABASE_URL"),
        gemini_api_key=get("GEMINI_API_KEY"),
        gemini_model=get("GEMINI_MODEL") or DEFAULT_GEMINI_MODEL,
        gemini_embed_model=get("GEMINI_EMBED_MODEL") or DEFAULT_GEMINI_EMBED_MODEL,
        retrieval=_flag("RETRIEVAL", retrieval) if retrieval else False,
        google_client_id=google_client_id,
        session_secret=session_secret,
        app_origin=app_origin,
        session_max_age_seconds=session_max_age_seconds,
        auth_allowed_google_subs=_comma_set(get("AUTH_ALLOWED_GOOGLE_SUBS")),
        auth_allowed_emails=_comma_set(get("AUTH_ALLOWED_EMAILS"), lowercase=True),
    )


def load_settings() -> Settings:
    """Build Settings from the real environment.

    Reads the repo-root .env first, so local runs (pytest, python -m
    nl2sql.db) see the same values docker-compose passes in. Variables
    already set in the environment win over .env, so a shell or Docker
    can still override any of them.
    """
    load_dotenv(ENV_FILE, override=False)
    return settings_from(os.environ)
