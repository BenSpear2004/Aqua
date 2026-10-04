"""Integration tests: confirm writes fail as nl2sql_reader.

These connect to the real database using DATABASE_URL from .env, and are
skipped when it is not set (teammates without a .env, or CI). They run
against whichever service DATABASE_URL points at, the bank or Pagila;
tests that only apply to one of them skip on the other.

Every write attempt runs inside a transaction that is rolled back, and
none of them would change a row even if it were allowed, so these tests
cannot damage the shared database even if the role were misconfigured.
"""

import psycopg
import pytest

from nl2sql.config import load_settings
from nl2sql.db import connect, describe_connection

SETTINGS = load_settings()

# A table with rows on each database.
READ = {"bank": "SELECT count(*) FROM trans", "pagila": "SELECT count(*) FROM film"}

# Each would be refused for lack of permission before doing anything.
# The first three are plain row writes, used again with read-only off.
WRITES = {
    "bank": [
        "INSERT INTO district (district_id, a2, a3, a4, a5, a6, a7, a8, a9, a10, a11, a13, a14, a16)"
        " SELECT 0, 'x', 'x', 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0 WHERE false",
        "UPDATE trans SET amount = amount WHERE trans_id = -1",
        "DELETE FROM trans WHERE trans_id = -1",
        "CREATE TABLE public.nl2sql_write_probe (id int)",
        "DROP TABLE trans",
        "TRUNCATE trans",
    ],
    "pagila": [
        "INSERT INTO actor (first_name, last_name) SELECT 'x', 'y' WHERE false",
        "UPDATE film SET title = title WHERE film_id = -1",
        "DELETE FROM film WHERE film_id = -1",
        "CREATE TABLE public.nl2sql_write_probe (id int)",
        "DROP TABLE film",
        "TRUNCATE film",
    ],
}
ALL_WRITES = [(db, sql) for db, writes in WRITES.items() for sql in writes]
ROW_WRITES = [(db, sql) for db, writes in WRITES.items() for sql in writes[:3]]


def test_connected_as_the_reader_not_the_admin(live_database: str) -> None:
    with connect(SETTINGS) as conn:
        info = describe_connection(conn)
    assert info["user"] == "nl2sql_reader"
    assert info["read_only"] == "on"


def test_reader_can_select(live_database: str) -> None:
    with connect(SETTINGS) as conn:
        (count,) = conn.execute(READ[live_database]).fetchone()
    assert count > 0


@pytest.mark.parametrize(("database", "sql"), ALL_WRITES)
def test_writes_fail(live_database: str, database: str, sql: str) -> None:
    if database != live_database:
        pytest.skip(f"written for the {database} service")
    with connect(SETTINGS) as conn:
        with pytest.raises(psycopg.Error):
            conn.execute(sql)
        conn.rollback()


@pytest.mark.parametrize(("database", "sql"), ROW_WRITES)
def test_writes_fail_even_with_read_only_switched_off(
    live_database: str, database: str, sql: str
) -> None:
    """Read-only mode can be switched off by the session itself; the
    missing write permissions are what must still stop the write."""
    if database != live_database:
        pytest.skip(f"written for the {database} service")
    with connect(SETTINGS) as conn:
        conn.read_only = False
        conn.execute("SET default_transaction_read_only = off")
        conn.commit()
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute(sql)
        conn.rollback()


@pytest.mark.parametrize(
    "sql",
    ["SELECT password FROM staff", "SELECT * FROM staff", "SELECT row_to_json(s) FROM staff s"],
)
def test_hidden_staff_columns_are_refused_by_the_database(on_pagila: None, sql: str) -> None:
    """Layer 2 for staff.password and staff.picture. Fails until
    db/05_hide_columns.sql has been run on this database."""
    with connect(SETTINGS) as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute(sql)
        conn.rollback()


def test_other_staff_columns_are_still_readable(on_pagila: None) -> None:
    with connect(SETTINGS) as conn:
        rows = conn.execute("SELECT first_name, last_name FROM staff").fetchall()
    assert len(rows) >= 1


def test_reader_can_search_but_not_write_the_retrieval_schema(on_pagila: None) -> None:
    """Needs db/04_retrieval.sql, which only the Pagila service has. The
    app searches these tables at question time; only nl2sql_indexer may
    change them."""
    with connect(SETTINGS) as conn:
        conn.execute("SELECT count(*) FROM retrieval.schema_doc").fetchone()
        conn.rollback()  # read_only can only change between transactions
        conn.read_only = False
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("DELETE FROM retrieval.example_query WHERE false")
        conn.rollback()
