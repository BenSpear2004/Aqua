"""Reject any generated SQL that is not a single, read-only SELECT.

This is one of two safety layers. The other is the database account the
app connects with, which should be granted SELECT only. Each covers the
other's failure: this code can have bugs, and a misconfigured account
would go unnoticed without this check. Rejecting here also gives a clear
reason that can be shown to the user or sent back to the model for a
retry, instead of a raw database error.

Why parse instead of searching the text for "DROP" or "DELETE": a text
search is fooled by comments, casing and a second statement after a
semicolon, and it wrongly rejects harmless queries such as
    SELECT title FROM film WHERE title = 'DROP ZONE'
Parsing tells us what the statement *is*, not what words it contains.

Checks the statement type, blocks dangerous functions and system
catalogs, and can restrict queries to a list of allowed tables.
limit_rows() then caps how many rows a validated query can return.
Column checks are not done yet.
"""

from __future__ import annotations

from collections.abc import Iterable

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError


class UnsafeQueryError(ValueError):
    """Raised when SQL fails validation.

    The message says why, in words a person or the model can act on.
    """


# What the whole statement is allowed to be. SetOperation is the parent
# of UNION, INTERSECT and EXCEPT, each of which combines SELECTs.
ALLOWED_STATEMENTS: tuple[type[exp.Expression], ...] = (
    exp.Select,
    exp.SetOperation,
)

# Nodes that must not appear anywhere in the tree, even nested inside an
# otherwise valid SELECT.
#   Lock    - FOR UPDATE / FOR SHARE. Still a SELECT, but it locks rows
#             and can block other users of the database.
#   Command - sqlglot's fallback for syntax it does not understand
#             (GRANT, CALL, REPLACE INTO). What we cannot parse, we
#             cannot prove safe.
#   Into    - SELECT ... INTO, which writes results to a table or file.
#   The rest are writes and schema changes. Databases do not allow them
#   inside a SELECT, so this is a second check, not the main one.
# Note: exp.Replace is deliberately absent. In sqlglot it is the
# harmless string function REPLACE(str, from, to), not REPLACE INTO.
FORBIDDEN_NODES: tuple[type[exp.Expression], ...] = (
    exp.Lock,
    exp.Command,
    exp.Into,
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Merge,
    exp.Create,
    exp.Drop,
    exp.Alter,
    exp.TruncateTable,
)

# Functions that are dangerous even inside a read-only SELECT. Compared
# lowercase. A read-only database account blocks most of the file and
# admin ones anyway; this is the second layer, and it also catches the
# slow-down ones, which need no special permission at all.
FORBIDDEN_FUNCTIONS: frozenset[str] = frozenset(
    {
        # Stall the database on purpose (denial of service).
        "sleep", "benchmark", "pg_sleep", "pg_sleep_for", "pg_sleep_until",
        # Read files on the database server.
        "load_file", "pg_read_file", "pg_read_binary_file", "pg_ls_dir",
        "pg_stat_file", "lo_import", "lo_export",
        # Reach other databases or run SQL passed in as a string, which
        # could hide a write the parser never sees.
        "dblink", "dblink_exec", "query_to_xml", "query_to_xml_and_xmlschema",
        # Change server settings or end other people's sessions.
        "set_config", "pg_reload_conf", "pg_terminate_backend",
        "pg_cancel_backend",
        # Hold locks that can block other users.
        "get_lock", "pg_advisory_lock", "pg_advisory_xact_lock",
    }
)


def _function_name(node: exp.Func) -> str:
    """Return a function call's name in lowercase.

    sqlglot parses functions it does not recognise, such as SLEEP or
    pg_sleep, as exp.Anonymous with the name attached. Known functions
    get their own classes, so ask those for their SQL name instead.
    """
    if isinstance(node, exp.Anonymous):
        return node.name.lower()
    return node.sql_name().lower()

# Built-in schemas that describe the database itself: every table, every
# column, and in places the database's users. The model gets the schema
# in its prompt and never needs these, so they are always blocked.
SYSTEM_SCHEMAS: frozenset[str] = frozenset(
    {"information_schema", "pg_catalog", "pg_toast", "mysql", "performance_schema", "sys"}
)


def _check_tables(statement: exp.Query, allowed: frozenset[str] | None) -> None:
    """Raise if the query reads a system catalog or a table not allowed.

    Names are compared lowercase, and schema prefixes are ignored for the
    allowlist, so film, public.film and sakila.film all count as film.
    """
    # Names defined by WITH inside this query. They look like tables but
    # are temporary results, and they can never have a schema prefix.
    cte_names = {cte.alias.lower() for cte in statement.find_all(exp.CTE)}

    for table in statement.find_all(exp.Table):
        name = table.name.lower()
        if not name:
            continue  # a table function like generate_series(); see FORBIDDEN_FUNCTIONS
        schemas = {table.db.lower(), table.catalog.lower()} - {""}
        if schemas & SYSTEM_SCHEMAS or (not schemas and name.startswith("pg_")):
            # Postgres finds pg_catalog tables like pg_user even without
            # the prefix, so unprefixed pg_ names are system tables too.
            raise UnsafeQueryError(f"Query reads a system catalog: {table.sql()}.")
        if not schemas and name in cte_names:
            continue
        if allowed is not None and name not in allowed:
            raise UnsafeQueryError(f"Query uses a table that is not allowed: {name}.")


def validate_sql(
    sql: str,
    dialect: str = "mysql",
    allowed_tables: Iterable[str] | None = None,
) -> exp.Query:
    """Return the parsed query if it is safe to run, otherwise raise.

    Returns the syntax tree rather than True so later checks (LIMIT
    injection, column checks) can work on it without parsing the same
    string a second time.

    `dialect` is a parameter because where Sakila will be hosted is not
    decided yet, and MySQL and PostgreSQL parse some SQL differently.

    `allowed_tables`, if given, is the only tables the query may read.
    Left as None, any table is allowed except system catalogs.
    """
    try:
        statements = sqlglot.parse(sql, read=dialect)
    except SqlglotError as exc:
        # SqlglotError is the parent of both ParseError (bad grammar) and
        # TokenError (text that cannot even be split into SQL words, such
        # as an unclosed quote). Catching only ParseError would let
        # TokenError escape as a crash instead of a clean rejection.
        raise UnsafeQueryError(f"SQL could not be parsed: {exc}") from exc
    except RecursionError as exc:
        # The parser calls itself once per nesting level, so thousands of
        # nested parentheses exceed Python's recursion limit.
        raise UnsafeQueryError("SQL is too deeply nested to parse.") from exc

    # Empty input and comment-only input parse to [None], not an error.
    statements = [s for s in statements if s is not None]
    if not statements:
        raise UnsafeQueryError("No SQL statement found.")
    if len(statements) > 1:
        raise UnsafeQueryError(
            f"Expected exactly one statement, found {len(statements)}."
        )

    statement = statements[0]
    if not isinstance(statement, ALLOWED_STATEMENTS):
        raise UnsafeQueryError(
            f"Only SELECT queries are allowed, got {statement.key.upper()}."
        )

    for node in statement.walk():
        if isinstance(node, FORBIDDEN_NODES):
            raise UnsafeQueryError(
                f"Query contains a forbidden operation: {node.key.upper()}."
            )
        if isinstance(node, exp.Func) and _function_name(node) in FORBIDDEN_FUNCTIONS:
            raise UnsafeQueryError(
                f"Query uses a forbidden function: {_function_name(node).upper()}."
            )

    allowed = None if allowed_tables is None else frozenset(t.lower() for t in allowed_tables)
    _check_tables(statement, allowed)

    return statement


# Most rows any query may return. Enough for any table a person would
# read in the panel; stops "list all contacts" pulling a whole table.
DEFAULT_MAX_ROWS = 1000


def limit_rows(query: exp.Query, max_rows: int = DEFAULT_MAX_ROWS) -> exp.Query:
    """Return a copy of a validated query that returns at most max_rows.

    A query with no limit gets one, a limit above max_rows is lowered,
    and a smaller limit is left alone. Only the outer query is changed,
    so ORDER BY, OFFSET and limits inside subqueries keep working.

    Kept separate from validate_sql: that decides whether a query is
    safe to run, this one bounds how much it can return.
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
