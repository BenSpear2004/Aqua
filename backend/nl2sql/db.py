"""Open database connections as the read-only role.

Every query the app runs goes through connect(), so the read-only
settings live in one place. The real protection is the database role
(nl2sql_reader has SELECT only); marking the session read-only here is
an extra layer on the app's side.

Run `python -m nl2sql.db` from backend/ to check the connection.
"""

from __future__ import annotations

import re
import sys

import psycopg

from nl2sql.config import Settings, load_settings

# Give up quickly if the database is unreachable rather than hanging a
# request; the server is a cloud service, so 10 seconds is generous.
CONNECT_TIMEOUT_SECONDS = 10


class DatabaseError(RuntimeError):
    """Raised when the app cannot connect to the database."""


def _redact(text: str) -> str:
    """Hide any password that appears in a connection URL inside text.

    Matches up to the last @ before the host, so a password containing
    an unencoded @ is hidden completely too.
    """
    return re.sub(r"(postgres(?:ql)?://[^:/@\s]+):\S*@", r"\1:***@", text)


def connect(settings: Settings) -> psycopg.Connection:
    """Open a read-only connection using DATABASE_URL.

    The caller closes it, normally with `with connect(settings) as conn:`.
    Error messages never include the password.
    """
    if not settings.database_url:
        raise DatabaseError("DATABASE_URL is not set. Copy .env.example to .env and fill it in.")
    try:
        conn = psycopg.connect(settings.database_url, connect_timeout=CONNECT_TIMEOUT_SECONDS)
    except psycopg.Error as exc:
        raise DatabaseError(f"Could not connect to the database: {_redact(str(exc))}") from exc
    # Every transaction on this connection is READ ONLY, so a write is
    # refused even if the role's own read-only default were switched off.
    conn.read_only = True
    return conn


def describe_connection(conn: psycopg.Connection) -> dict[str, str]:
    """Report who we are connected as and whether the session is read-only.

    Used by the smoke test below; useful for a health check too.
    """
    user, read_only, version = conn.execute(
        "SELECT current_user, current_setting('transaction_read_only'), "
        "current_setting('server_version')"
    ).fetchone()
    return {"user": user, "read_only": read_only, "server_version": version}


def main() -> int:
    """Connection smoke test: print who we connected as, never the URL."""
    try:
        with connect(load_settings()) as conn:
            info = describe_connection(conn)
    except DatabaseError as exc:
        print(exc)
        return 1
    print(f"Connected as {info['user']} (read only: {info['read_only']}), "
          f"PostgreSQL {info['server_version']}")
    if info["user"] == "tsdbadmin":
        print("Warning: this is the admin account. The app must use nl2sql_reader.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
