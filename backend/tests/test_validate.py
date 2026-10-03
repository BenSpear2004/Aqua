"""Tests for nl2sql/validate.py.

These run without a database or an API key: the validator only parses
text, so every case here is a fixed string. That makes this suite fast
and safe to run on any machine, any time.

The rejected cases double as a red-team suite. When someone finds a new
way to sneak a write past the validator, add it here first, watch it
fail, then fix the validator.
"""

import pytest
from sqlglot import exp

from nl2sql.validate import UnsafeQueryError, validate_sql

# Queries the model could reasonably produce. All must pass.
SAFE = [
    "SELECT * FROM film",
    "select title from film;",  # lowercase, trailing semicolon
    "SELECT title FROM film WHERE title = 'DROP ZONE'",  # scary word in data
    "SELECT REPLACE(title, 'A', 'B') FROM film",  # REPLACE the function
    "SELECT 1 UNION SELECT 2",
    "WITH x AS (SELECT 1 AS a) SELECT a FROM x",
    "SELECT * FROM film /* ; DROP TABLE film */",  # attack inside a comment
    "SELECT f.title FROM film f JOIN film_actor fa ON f.film_id = fa.film_id",
    "SELECT rating, COUNT(*) AS n FROM film GROUP BY rating ORDER BY n DESC",
]

# Each unsafe query, paired with a fragment of the error we expect. The
# fragment proves it was rejected for the RIGHT reason, not by accident.
UNSAFE = [
    ("", "No SQL statement"),
    ("-- only a comment", "No SQL statement"),
    ("SELECT 1; DROP TABLE film", "exactly one statement"),
    ("DROP TABLE film", "got DROP"),
    ("DELETE FROM film WHERE film_id = 1", "got DELETE"),
    ("UPDATE film SET title = 'x'", "got UPDATE"),
    ("INSERT INTO film (title) SELECT 'x'", "got INSERT"),
    ("SHOW TABLES", "got SHOW"),
    ("EXPLAIN SELECT 1", "got DESCRIBE"),
    ("GRANT ALL ON *.* TO someone", "got COMMAND"),
    ("REPLACE INTO film (film_id) VALUES (1)", "got COMMAND"),
    ("SELECT * FROM film FOR UPDATE", "forbidden operation: LOCK"),
    ("SELECT * FROM film LOCK IN SHARE MODE", "forbidden operation: LOCK"),
    ("SELECT * INTO OUTFILE '/tmp/x' FROM film", "could not be parsed"),
    ("SELEC * FROM film", "could not be parsed"),
    # Text the tokenizer cannot split into SQL words (TokenError). Found
    # when a model reply contained prose like "let's" before the SQL.
    ("SELECT 'unterminated", "could not be parsed"),
    ('SELECT "unterminated', "could not be parsed"),
    ("Let's think. SELECT 1", "could not be parsed"),
    ("SELECT 1 /* never closed", "could not be parsed"),
    # Deep enough to exceed Python's recursion limit inside the parser.
    pytest.param(
        "SELECT " + "(" * 3000 + "1" + ")" * 3000,
        "too deeply nested",
        id="3000-nested-parentheses",  # short name; the SQL is 6000 chars
    ),
]


@pytest.mark.parametrize("sql", SAFE)
def test_safe_queries_pass(sql: str) -> None:
    assert isinstance(validate_sql(sql), exp.Query)


@pytest.mark.parametrize(("sql", "reason"), UNSAFE)
def test_unsafe_queries_are_rejected(sql: str, reason: str) -> None:
    with pytest.raises(UnsafeQueryError, match=reason):
        validate_sql(sql)


def test_error_is_a_value_error() -> None:
    """Callers that only know about ValueError still catch it."""
    with pytest.raises(ValueError):
        validate_sql("DROP TABLE film")


def test_returns_tree_of_the_query() -> None:
    """Later stages rely on getting the parsed query back, not a bool."""
    tree = validate_sql("SELECT title FROM film")
    assert [t.name for t in tree.find_all(exp.Table)] == ["film"]
