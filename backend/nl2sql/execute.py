"""Run validated SQL against the database and return the rows.

Takes the parsed query that validate_sql() returns, not a SQL string, so
nothing reaches the database without going through the validator first.
Every query is capped at a row limit, and the result says whether rows
were cut off. The connection comes from db.py, so it is the read-only
role in a read-only transaction, and the role's statement_timeout stops
any query that runs too long.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import psycopg
from sqlglot import exp

from nl2sql.config import Settings
from nl2sql.db import connect
from nl2sql.validate import UnsafeQueryError

# Most rows any query may return. Enough for any table a person would
# read in the panel; stops "list all customers" pulling a whole table.
DEFAULT_MAX_ROWS = 1000


class QueryError(RuntimeError):
    """The database rejected or could not finish a validated query.

    For example an unknown column, a type mismatch, or the statement
    timeout. The message is the database's own first line, which is
    useful to show the user or send back to the model for a retry.
    """


@dataclass(frozen=True)
class QueryResult:
    """What a query returned.

    `sql` is the statement with the row limit applied, as a user should
    see it. `truncated` is True when there were more rows than max_rows.
    """

    sql: str
    columns: list[str]
    rows: list[tuple[Any, ...]]
    truncated: bool


def limit_rows(query: exp.Query, max_rows: int = DEFAULT_MAX_ROWS) -> exp.Query:
    """Return a copy of a validated query that returns at most max_rows.

    A query with no limit gets one, a limit above max_rows is lowered,
    and a smaller limit is left alone. Only the outer query is changed,
    so ORDER BY, OFFSET and limits inside subqueries keep working.
    """
    current = query.args.get("limit")
    if current is None:
        requested = None
    elif isinstance(current, exp.Fetch):
        # Postgres FETCH FIRST n ROWS ONLY, another way to write LIMIT n.
        requested = current.args.get("count")
    else:
        requested = current.expression  # None for LIMIT ALL

    if requested is None:
        return query.limit(max_rows)
    if not (isinstance(requested, exp.Literal) and requested.is_int):
        # An expression like LIMIT 1+1. Rare, and guessing its value
        # could raise the limit the model asked for, so refuse it.
        raise UnsafeQueryError("LIMIT must be a whole number.")
    return query.limit(min(int(requested.this), max_rows))


def execute(
    query: exp.Query,
    settings: Settings,
    max_rows: int = DEFAULT_MAX_ROWS,
    dialect: str = "postgres",
) -> QueryResult:
    """Run a validated query and return its columns and rows.

    Asks the database for one row more than max_rows: if that extra row
    comes back, the result was cut off. Raises QueryError if the database
    rejects the query and db.DatabaseError if it cannot be reached.
    """
    if not isinstance(query, exp.Query):
        raise TypeError("execute() takes the parsed query from validate_sql(), not a string.")

    probe_sql = limit_rows(query, max_rows + 1).sql(dialect=dialect)
    with connect(settings) as conn:
        try:
            cursor = conn.execute(probe_sql)
            rows = cursor.fetchall()
        except psycopg.Error as exc:
            raise QueryError(str(exc).strip().splitlines()[0]) from exc
        columns = [column.name for column in cursor.description or []]

    return QueryResult(
        sql=limit_rows(query, max_rows).sql(dialect=dialect),
        columns=columns,
        rows=rows[:max_rows],
        truncated=len(rows) > max_rows,
    )
