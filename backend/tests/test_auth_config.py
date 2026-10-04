"""Tests for Google sign-in configuration without reading local secrets."""

import pytest

from nl2sql.config import ConfigError, Settings, settings_from


def test_auth_defaults_do_not_grant_access() -> None:
    settings = settings_from({})
    assert settings.google_client_id == ""
    assert settings.session_secret == ""
    assert settings.app_origin == "https://aqua-ai.us"
    assert settings.session_max_age_seconds == 3600
    assert settings.auth_allowed_google_subs == frozenset()
    assert settings.auth_allowed_emails == frozenset()
    assert Settings().auth_allowed_google_subs == frozenset()
    assert Settings().auth_allowed_emails == frozenset()


def test_blank_auth_values_keep_safe_defaults() -> None:
    settings = settings_from(
        {
            "GOOGLE_CLIENT_ID": "  ",
            "SESSION_SECRET": "",
            "APP_ORIGIN": " ",
            "SESSION_MAX_AGE_SECONDS": " ",
            "AUTH_ALLOWED_GOOGLE_SUBS": " , , ",
            "AUTH_ALLOWED_EMAILS": " , ",
        }
    )
    assert settings == settings_from({})


def test_auth_configuration_is_read_and_normalized() -> None:
    client_id = "123456789-test_client.apps.googleusercontent.com"
    session_secret = "a-test-session-secret-with-at-least-32-characters"
    settings = settings_from(
        {
            "GOOGLE_CLIENT_ID": f" {client_id} ",
            "SESSION_SECRET": f" {session_secret} ",
            "APP_ORIGIN": " HTTPS://AQUA-AI.US:443 ",
            "SESSION_MAX_AGE_SECONDS": " 7200 ",
            "AUTH_ALLOWED_GOOGLE_SUBS": " Subject_A, Subject_a, Subject_A, , ",
            "AUTH_ALLOWED_EMAILS": (
                " ADMIN@Example.com, analyst@example.com, ADMIN@EXAMPLE.COM, , "
            ),
        }
    )
    assert settings.google_client_id == client_id
    assert settings.session_secret == session_secret
    assert session_secret not in repr(settings)
    assert settings.app_origin == "https://aqua-ai.us"
    assert settings.session_max_age_seconds == 7200
    assert settings.auth_allowed_google_subs == frozenset({"Subject_A", "Subject_a"})
    assert settings.auth_allowed_emails == frozenset(
        {"admin@example.com", "analyst@example.com"}
    )


@pytest.mark.parametrize(
    "value",
    [
        "AQ.not-a-google-client-id",
        "test.apps.googleusercontent.com.evil.test",
        ".apps.googleusercontent.com",
        "https://test.apps.googleusercontent.com",
        "test.apps.googleusercontent.com,other.apps.googleusercontent.com",
        "test client.apps.googleusercontent.com",
    ],
)
def test_invalid_google_client_ids_are_rejected_without_echoing(value: str) -> None:
    with pytest.raises(ConfigError, match="GOOGLE_CLIENT_ID") as error:
        settings_from({"GOOGLE_CLIENT_ID": value})
    assert value not in str(error.value)


@pytest.mark.parametrize("secret", ["private-secret", "x" * 31])
def test_short_session_secret_errors_do_not_expose_secret(secret: str) -> None:
    with pytest.raises(ConfigError, match="SESSION_SECRET") as error:
        settings_from({"SESSION_SECRET": secret})
    assert secret not in str(error.value)


def test_minimum_length_session_secret_is_accepted_and_hidden() -> None:
    secret = "x" * 32
    settings = settings_from({"SESSION_SECRET": secret})
    assert settings.session_secret == secret
    assert secret not in repr(settings)


@pytest.mark.parametrize("seconds", [300, 3600, 86400])
def test_session_lifetime_accepts_supported_bounds(seconds: int) -> None:
    settings = settings_from({"SESSION_MAX_AGE_SECONDS": str(seconds)})
    assert settings.session_max_age_seconds == seconds


@pytest.mark.parametrize("value", ["299", "86401", "0", "-1", "3600.0", "1e3", "bad"])
def test_invalid_session_lifetimes_are_rejected(value: str) -> None:
    with pytest.raises(ConfigError, match="SESSION_MAX_AGE_SECONDS"):
        settings_from({"SESSION_MAX_AGE_SECONDS": value})


@pytest.mark.parametrize(
    ("origin", "expected"),
    [
        ("https://aqua-ai.us", "https://aqua-ai.us"),
        ("https://WWW.AQUA-AI.US:8443", "https://www.aqua-ai.us:8443"),
        ("https://aqua-ai.us:443", "https://aqua-ai.us"),
        ("http://localhost:5173", "http://localhost:5173"),
        ("http://LOCALHOST:80", "http://localhost"),
        ("http://127.0.0.1:5173", "http://127.0.0.1:5173"),
        ("http://[::1]:5173", "http://[::1]:5173"),
        ("https://[::1]", "https://[::1]"),
    ],
)
def test_app_origin_accepts_https_and_local_http(origin: str, expected: str) -> None:
    assert settings_from({"APP_ORIGIN": origin}).app_origin == expected


@pytest.mark.parametrize(
    "origin",
    [
        "aqua-ai.us",
        "//aqua-ai.us",
        "http://aqua-ai.us",
        "http://localhost.evil.test",
        "http://127.0.0.2",
        "ftp://aqua-ai.us",
        "https://aqua-ai.us/",
        "https://aqua-ai.us/auth",
        "https://aqua-ai.us?client=example",
        "https://aqua-ai.us?",
        "https://aqua-ai.us#login",
        "https://aqua-ai.us#",
        "https://user:private-password@aqua-ai.us",
        "https://aqua-ai.us:0",
        "https://aqua-ai.us:65536",
        "https://aqua-ai.us:",
        "https://aqua-ai.us,evil.test",
        "https://aqua-ai.us\n.evil.test",
        "https://aqua-ai.us\\evil.test",
        "https://aqua..us",
        "https://[::1]evil",
        "https://[v1.foo]",
        "https://[::1",
        "https://[fe80::1%eth0]",
    ],
)
def test_invalid_app_origins_are_rejected_without_echoing(origin: str) -> None:
    with pytest.raises(ConfigError, match="APP_ORIGIN") as error:
        settings_from({"APP_ORIGIN": origin})
    assert origin not in str(error.value)
    assert "private-password" not in str(error.value)
