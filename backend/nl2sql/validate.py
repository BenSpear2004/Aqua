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

Checks the statement type and blocks a list of dangerous functions.
Table allowlists, column checks and LIMIT injection are not done yet.
"""

from __future__ import annotations

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


def validate_sql(sql: str, dialect: str = "mysql") -> exp.Query:
    """Return the parsed query if it is safe to run, otherwise raise.

    Returns the syntax tree rather than True so later checks (LIMIT
    injection, column checks) can work on it without parsing the same
    string a second time.

    `dialect` is a parameter because where Sakila will be hosted is not
    decided yet, and MySQL and PostgreSQL parse some SQL differently.
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

    return statement
