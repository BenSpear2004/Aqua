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
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

DEFAULT_OLLAMA_BASE_URL = "http://127.0.0.1:11434"
DEFAULT_OLLAMA_MODEL = "qwen3:8b"
DEFAULT_GEMINI_MODEL = "gemma-4-31b-it"
DEFAULT_GEMINI_EMBED_MODEL = "gemini-embedding-2"

# Where SQL generation runs. Ollama is the default; Gemini is the backup,
# or the demo model when a paid key is set. The API can also pick one per
# request.
PROVIDERS = ("ollama", "gemini")
DEFAULT_LLM_PROVIDER = "ollama"

# The repo-root .env, two folders up from this file (backend/nl2sql/).
# Inside the Docker image this path does not exist, which is fine:
# docker-compose passes the same values in as environment variables.
ENV_FILE = Path(__file__).resolve().parents[2] / ".env"

_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}


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
    # Gemini API: embeddings for retrieval, and SQL generation when
    # llm_provider is "gemini". gemma-4-31b-it is free; a paid key can
    # use a Gemini model instead.
    gemini_api_key: str = field(default="", repr=False)
    gemini_model: str = DEFAULT_GEMINI_MODEL
    gemini_embed_model: str = DEFAULT_GEMINI_EMBED_MODEL
    # Which provider llm.py sends prompts to: "ollama" or "gemini".
    llm_provider: str = DEFAULT_LLM_PROVIDER
    # Retrieve relevant tables and examples per question (Phase 4). Off
    # until the indexer has run and the eval shows it helps.
    retrieval: bool = False


def _flag(name: str, value: str) -> bool:
    """Parse an on/off environment variable, rejecting anything unclear."""
    lowered = value.strip().lower()
    if lowered in _TRUE:
        return True
    if lowered in _FALSE:
        return False
    raise ConfigError(f"{name} must be true or false, got {value!r}.")


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

    provider = get("LLM_PROVIDER").lower() or DEFAULT_LLM_PROVIDER
    if provider not in PROVIDERS:
        raise ConfigError(
            f"LLM_PROVIDER must be one of {', '.join(PROVIDERS)}, got {provider!r}."
        )

    think = get("OLLAMA_THINK")
    retrieval = get("RETRIEVAL")
    return Settings(
        ollama_base_url=base_url.rstrip("/"),
        ollama_model=get("OLLAMA_MODEL") or DEFAULT_OLLAMA_MODEL,
        ollama_think=_flag("OLLAMA_THINK", think) if think else True,
        database_url=get("DATABASE_URL"),
        indexer_database_url=get("INDEXER_DATABASE_URL"),
        gemini_api_key=get("GEMINI_API_KEY"),
        gemini_model=get("GEMINI_MODEL") or DEFAULT_GEMINI_MODEL,
        gemini_embed_model=get("GEMINI_EMBED_MODEL") or DEFAULT_GEMINI_EMBED_MODEL,
        llm_provider=provider,
        retrieval=_flag("RETRIEVAL", retrieval) if retrieval else False,
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
