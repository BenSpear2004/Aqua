"""Tests for nl2sql/config.py.

Every test passes a plain dict to settings_from, so none of them depend
on environment variables set on the machine running them.
"""

import dataclasses

import pytest

from nl2sql.config import ConfigError, Settings, settings_from


def test_defaults_when_nothing_is_set() -> None:
    settings = settings_from({})
    assert settings.ollama_base_url == "http://127.0.0.1:11434"
    assert settings.ollama_model == "qwen3:8b"
    assert settings.ollama_think is True
    assert settings.database_url == ""


def test_blank_values_fall_back_to_defaults() -> None:
    settings = settings_from({"OLLAMA_MODEL": "   ", "OLLAMA_THINK": ""})
    assert settings.ollama_model == "qwen3:8b"
    assert settings.ollama_think is True


def test_values_are_read_and_trimmed() -> None:
    settings = settings_from(
        {
            "OLLAMA_BASE_URL": " http://10.0.0.5:11434 ",
            "OLLAMA_MODEL": "qwen3:4b",
            "DATABASE_URL": "mysql://app:pw@db/sakila",
        }
    )
    assert settings.ollama_base_url == "http://10.0.0.5:11434"
    assert settings.ollama_model == "qwen3:4b"
    assert settings.database_url == "mysql://app:pw@db/sakila"


def test_trailing_slash_is_removed_from_url() -> None:
    settings = settings_from({"OLLAMA_BASE_URL": "http://10.0.0.5:11434/"})
    assert settings.ollama_base_url == "http://10.0.0.5:11434"


def test_url_without_scheme_is_rejected() -> None:
    with pytest.raises(ConfigError, match="OLLAMA_BASE_URL"):
        settings_from({"OLLAMA_BASE_URL": "10.0.0.5:11434"})


@pytest.mark.parametrize("value", ["true", "TRUE", "1", "yes", "on"])
def test_think_on_values(value: str) -> None:
    assert settings_from({"OLLAMA_THINK": value}).ollama_think is True


@pytest.mark.parametrize("value", ["false", "False", "0", "no", "off"])
def test_think_off_values(value: str) -> None:
    assert settings_from({"OLLAMA_THINK": value}).ollama_think is False


def test_unclear_think_value_is_rejected() -> None:
    """A typo should be an error, not a silent change in model behavior."""
    with pytest.raises(ConfigError, match="OLLAMA_THINK"):
        settings_from({"OLLAMA_THINK": "maybe"})


def test_database_password_never_appears_when_printed() -> None:
    settings = settings_from({"DATABASE_URL": "mysql://app:s3cret@db/sakila"})
    assert "s3cret" not in repr(settings)
    assert "qwen3:8b" in repr(settings)  # non-secrets still show


def test_settings_cannot_be_changed() -> None:
    settings = settings_from({})
    with pytest.raises(dataclasses.FrozenInstanceError):
        settings.ollama_model = "something-else"  # type: ignore[misc]


def test_settings_can_be_built_by_hand() -> None:
    """Other modules' tests do this instead of going through the environment."""
    settings = Settings(ollama_model="m", ollama_think=False)
    assert settings.ollama_model == "m"
    assert settings.ollama_base_url == "http://127.0.0.1:11434"


# ---- Gemini, indexer and retrieval (Phase 4) ----


def test_gemini_and_retrieval_defaults() -> None:
    settings = settings_from({})
    assert settings.gemini_api_key == ""
    assert settings.gemini_model == "gemma-4-31b-it"
    assert settings.gemini_embed_model == "gemini-embedding-2"
    assert settings.indexer_database_url == ""
    assert settings.retrieval is False  # off until the index is built


def test_gemini_indexer_and_retrieval_are_read() -> None:
    settings = settings_from(
        {
            "GEMINI_API_KEY": " key ",
            "GEMINI_MODEL": "gemma-4-26b-a4b-it",
            "GEMINI_EMBED_MODEL": "gemini-embedding-001",
            "INDEXER_DATABASE_URL": "postgresql://nl2sql_indexer:pw@db/tsdb",
            "RETRIEVAL": "on",
        }
    )
    assert settings.gemini_api_key == "key"
    assert settings.gemini_model == "gemma-4-26b-a4b-it"
    assert settings.gemini_embed_model == "gemini-embedding-001"
    assert settings.indexer_database_url == "postgresql://nl2sql_indexer:pw@db/tsdb"
    assert settings.retrieval is True


def test_unclear_retrieval_value_is_rejected() -> None:
    with pytest.raises(ConfigError, match="RETRIEVAL"):
        settings_from({"RETRIEVAL": "sometimes"})


def test_secrets_never_appear_when_printed() -> None:
    settings = settings_from({"GEMINI_API_KEY": "sk-secret", "INDEXER_DATABASE_URL": "postgresql://i:pw2@h/db"})
    assert "sk-secret" not in repr(settings)
    assert "pw2" not in repr(settings)


def test_fallback_is_on_unless_switched_off() -> None:
    assert settings_from({}).llm_fallback is True
    assert settings_from({"LLM_FALLBACK": "off"}).llm_fallback is False
    with pytest.raises(ConfigError, match="LLM_FALLBACK"):
        settings_from({"LLM_FALLBACK": "maybe"})


def test_answer_size_and_cache_settings() -> None:
    settings = settings_from({})
    assert settings.answer_size_rules is True
    assert settings.answer_cache_seconds == 600
    off = settings_from({"ANSWER_SIZE_RULES": "off", "ANSWER_CACHE_SECONDS": "0"})
    assert off.answer_size_rules is False and off.answer_cache_seconds == 0
    with pytest.raises(ConfigError, match="ANSWER_CACHE_SECONDS"):
        settings_from({"ANSWER_CACHE_SECONDS": "ten"})
    with pytest.raises(ConfigError, match="ANSWER_CACHE_SECONDS"):
        settings_from({"ANSWER_CACHE_SECONDS": "-5"})
