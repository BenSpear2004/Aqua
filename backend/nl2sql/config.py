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
    # Empty until we decide where Sakila is hosted. Hidden when printed
    # because database URLs usually contain the password.
    database_url: str = field(default="", repr=False)


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

    think = get("OLLAMA_THINK")
    return Settings(
        ollama_base_url=base_url.rstrip("/"),
        ollama_model=get("OLLAMA_MODEL") or DEFAULT_OLLAMA_MODEL,
        ollama_think=_flag("OLLAMA_THINK", think) if think else True,
        database_url=get("DATABASE_URL"),
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
