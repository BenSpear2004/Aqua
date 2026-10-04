"""Tests for nl2sql/db.py that need no database.

psycopg.connect is replaced with a stand-in, so these check our own
logic: missing settings, error messages without passwords, and that
every connection is marked read-only.
"""

import psycopg
import pytest

from nl2sql import db
from nl2sql.config import Settings
from nl2sql.db import DatabaseError, _redact, connect

URL = "postgresql://nl2sql_reader:s3cret@db.example.test:5432/tsdb?sslmode=require"


class FakeConnection:
    """Stands in for a psycopg connection; only what connect() touches."""

    read_only = False


def test_missing_url_is_a_clear_error() -> None:
    with pytest.raises(DatabaseError, match="DATABASE_URL is not set"):
        connect(Settings(database_url=""))


def test_connection_is_marked_read_only(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    def fake_connect(url, **kwargs):
        calls.append((url, kwargs))
        return FakeConnection()

    monkeypatch.setattr(db.psycopg, "connect", fake_connect)
    conn = connect(Settings(database_url=URL))

    assert conn.read_only is True
    (url, kwargs), = calls
    assert url == URL
    assert kwargs["connect_timeout"] == db.CONNECT_TIMEOUT_SECONDS


def test_connection_failure_hides_the_password(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_connect(url, **kwargs):
        raise psycopg.OperationalError(f"could not connect using {url}")

    monkeypatch.setattr(db.psycopg, "connect", fake_connect)
    with pytest.raises(DatabaseError) as info:
        connect(Settings(database_url=URL))

    assert "s3cret" not in str(info.value)
    assert "nl2sql_reader:***@" in str(info.value)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("postgresql://u:pw@host/db", "postgresql://u:***@host/db"),
        ("postgres://u:pw@host/db", "postgres://u:***@host/db"),
        ("failed for postgresql://u:p@ss@host/db", "failed for postgresql://u:***@host/db"),
        ("no url here", "no url here"),
        ("postgresql://host/db", "postgresql://host/db"),  # no password to hide
    ],
)
def test_redact(text: str, expected: str) -> None:
    assert _redact(text) == expected


def test_smoke_test_refuses_the_admin_account(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    class FakeCtx:
        def __enter__(self):
            return object()

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(db, "connect", lambda settings: FakeCtx())
    monkeypatch.setattr(
        db, "describe_connection", lambda conn: {"user": "tsdbadmin", "read_only": "on", "server_version": "18"}
    )
    assert db.main() == 1
    assert "admin account" in capsys.readouterr().out


def test_smoke_test_reports_connection_errors(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    def failing_connect(settings):
        raise DatabaseError("DATABASE_URL is not set.")

    monkeypatch.setattr(db, "connect", failing_connect)
    assert db.main() == 1
    assert "not set" in capsys.readouterr().out
