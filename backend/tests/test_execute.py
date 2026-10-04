"""Tests for nl2sql/execute.py.

The row-limit and unit tests need no database. The tests marked
`needs_db` run against the real database as nl2sql_reader and are
skipped when DATABASE_URL is not set.
"""

import psycopg
import pytest

from nl2sql import execute as execute_module
from nl2sql.config import Settings, load_settings
from nl2sql.db import DatabaseError
from nl2sql.execute import DEFAULT_MAX_ROWS, QueryError, execute, limit_rows
from nl2sql.validate import UnsafeQueryError, validate_sql

# ---- row limit (moved here from test_validate.py) ----


def limited(sql: str, dialect: str = "postgres", max_rows: int = 1000) -> str:
    """Validate, apply the row limit, and return the SQL that would run."""
    return limit_rows(validate_sql(sql, dialect=dialect), max_rows).sql(dialect=dialect)


@pytest.mark.parametrize(
    ("dialect", "sql", "expected"),
    [
        ("postgres", "SELECT title FROM film", "SELECT title FROM film LIMIT 1000"),
        ("postgres", "SELECT title FROM film LIMIT 5", "SELECT title FROM film LIMIT 5"),
        ("postgres", "SELECT title FROM film LIMIT 5000", "SELECT title FROM film LIMIT 1000"),
        (
            "postgres",
            "SELECT title FROM film ORDER BY title LIMIT 5000",
            "SELECT title FROM film ORDER BY title LIMIT 1000",
        ),
        (
            "postgres",
            "SELECT title FROM film LIMIT 5000 OFFSET 20",
            "SELECT title FROM film LIMIT 1000 OFFSET 20",
        ),
        ("postgres", "SELECT 1 UNION SELECT 2", "SELECT 1 UNION SELECT 2 LIMIT 1000"),
        # The inner limit is left alone; only the outer query is capped.
        (
            "postgres",
            "SELECT * FROM (SELECT title FROM film LIMIT 2000) AS t",
            "SELECT * FROM (SELECT title FROM film LIMIT 2000) AS t LIMIT 1000",
        ),
        (
            "postgres",
            "SELECT title FROM film FETCH FIRST 5000 ROWS ONLY",
            "SELECT title FROM film LIMIT 1000",
        ),
        ("postgres", "SELECT title FROM film FETCH FIRST 3 ROWS ONLY", "SELECT title FROM film LIMIT 3"),
        ("postgres", "SELECT title FROM film LIMIT ALL", "SELECT title FROM film LIMIT 1000"),
        # MySQL's "LIMIT offset, count" keeps its meaning.
        ("mysql", "SELECT title FROM film LIMIT 10, 5", "SELECT title FROM film LIMIT 5 OFFSET 10"),
    ],
)
def test_row_limit(dialect: str, sql: str, expected: str) -> None:
    assert limited(sql, dialect=dialect) == expected


def test_custom_max_rows() -> None:
    assert limited("SELECT title FROM film", max_rows=50) == "SELECT title FROM film LIMIT 50"


def test_default_max_rows_is_used() -> None:
    tree = limit_rows(validate_sql("SELECT title FROM film"))
    assert tree.sql() == f"SELECT title FROM film LIMIT {DEFAULT_MAX_ROWS}"


def test_expression_limit_is_rejected() -> None:
    with pytest.raises(UnsafeQueryError, match="whole number"):
        limited("SELECT title FROM film LIMIT 1+1")


def test_original_query_is_not_changed() -> None:
    """The caller may still want to log exactly what the model wrote."""
    tree = validate_sql("SELECT title FROM film LIMIT 5000")
    limit_rows(tree)
    assert tree.sql() == "SELECT title FROM film LIMIT 5000"


# ---- execute, with a stand-in connection ----


class FakeCursor:
    def __init__(self, columns: list[str], rows: list[tuple]):
        self.description = [type("Column", (), {"name": name})() for name in columns]
        self._rows = rows

    def fetchall(self) -> list[tuple]:
        return self._rows


class FakeConnection:
    """Records the SQL it is given; returns canned rows or raises."""

    def __init__(self, columns=(), rows=(), error: Exception | None = None):
        self.executed: list[str] = []
        self._cursor = FakeCursor(list(columns), list(rows))
        self._error = error

    def execute(self, sql: str) -> FakeCursor:
        self.executed.append(sql)
        if self._error is not None:
            raise self._error
        return self._cursor

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def use_fake(monkeypatch: pytest.MonkeyPatch, conn: FakeConnection) -> None:
    monkeypatch.setattr(execute_module, "connect", lambda settings: conn)


SETTINGS = Settings(database_url="postgresql://u:p@db.example.test/tsdb")


def test_asks_for_one_extra_row_and_reports_columns(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = FakeConnection(columns=["title"], rows=[("A",), ("B",)])
    use_fake(monkeypatch, conn)

    result = execute(validate_sql("SELECT title FROM film"), SETTINGS, max_rows=10)

    assert conn.executed == ["SELECT title FROM film LIMIT 11"]
    assert result.columns == ["title"]
    assert result.rows == [("A",), ("B",)]
    assert result.truncated is False
    assert result.sql == "SELECT title FROM film LIMIT 10"  # what the user sees


def test_extra_row_means_truncated(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = FakeConnection(columns=["n"], rows=[(i,) for i in range(4)])
    use_fake(monkeypatch, conn)

    result = execute(validate_sql("SELECT film_id AS n FROM film"), SETTINGS, max_rows=3)

    assert result.rows == [(0,), (1,), (2,)]
    assert result.truncated is True


def test_database_rejection_becomes_query_error(monkeypatch: pytest.MonkeyPatch) -> None:
    error = psycopg.errors.UndefinedColumn('column "nope" does not exist\nLINE 1: SELECT nope ...')
    use_fake(monkeypatch, FakeConnection(error=error))

    with pytest.raises(QueryError, match='column "nope" does not exist') as info:
        execute(validate_sql("SELECT nope FROM film"), SETTINGS)
    assert "LINE 1" not in str(info.value)  # first line only


def test_connection_errors_are_not_disguised(monkeypatch: pytest.MonkeyPatch) -> None:
    def failing_connect(settings):
        raise DatabaseError("Could not connect to the database: timeout")

    monkeypatch.setattr(execute_module, "connect", failing_connect)
    with pytest.raises(DatabaseError):
        execute(validate_sql("SELECT 1"), SETTINGS)


def test_raw_strings_are_refused() -> None:
    """Only validate_sql() output may reach the database."""
    with pytest.raises(TypeError, match="validate_sql"):
        execute("SELECT * FROM film", SETTINGS)  # type: ignore[arg-type]


# ---- execute against the real database ----

REAL = load_settings()
needs_db = pytest.mark.skipif(
    not REAL.database_url,
    reason="DATABASE_URL is not set; these tests need the real database",
)


@needs_db
def test_real_query_returns_rows() -> None:
    result = execute(validate_sql("SELECT count(*) AS films FROM film"), REAL)
    assert result.columns == ["films"]
    assert result.rows[0][0] > 0
    assert result.truncated is False


@needs_db
def test_real_truncation() -> None:
    result = execute(validate_sql("SELECT film_id FROM film ORDER BY film_id"), REAL, max_rows=10)
    assert len(result.rows) == 10
    assert result.truncated is True


@needs_db
def test_real_smaller_limit_is_kept() -> None:
    result = execute(validate_sql("SELECT film_id FROM film LIMIT 5"), REAL, max_rows=10)
    assert len(result.rows) == 5
    assert result.truncated is False


@needs_db
def test_real_unknown_column_is_a_query_error() -> None:
    with pytest.raises(QueryError, match="does not exist"):
        execute(validate_sql("SELECT no_such_column FROM film"), REAL)


@needs_db
def test_real_statement_timeout_is_a_query_error() -> None:
    """A query that runs past the role's 10 second limit is cancelled.
    Takes about 10 seconds."""
    slow = "SELECT count(*) FROM film a CROSS JOIN film b CROSS JOIN film c CROSS JOIN film d"
    with pytest.raises(QueryError, match="statement timeout"):
        execute(validate_sql(slow), REAL)
