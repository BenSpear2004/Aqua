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

from nl2sql.validate import (
    DEFAULT_MAX_ROWS,
    FORBIDDEN_FUNCTIONS,
    UnsafeQueryError,
    limit_rows,
    validate_sql,
)

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


# ---- dangerous functions ----

# (dialect, sql, function name expected in the error)
FORBIDDEN_FUNCTION_CASES = [
    ("mysql", "SELECT SLEEP(5)", "SLEEP"),
    ("mysql", "SELECT sleep(5)", "SLEEP"),  # any case
    ("mysql", "SELECT `SLEEP`(5)", "SLEEP"),  # quoted name
    ("mysql", "SELECT title FROM film WHERE SLEEP(1) = 0", "SLEEP"),  # hidden in WHERE
    ("mysql", "SELECT BENCHMARK(1000000, MD5('a'))", "BENCHMARK"),
    ("mysql", "SELECT LOAD_FILE('/etc/passwd')", "LOAD_FILE"),
    ("postgres", "SELECT pg_sleep(5)", "PG_SLEEP"),
    ("postgres", "SELECT pg_catalog.pg_sleep(5)", "PG_SLEEP"),  # schema prefix
    ("postgres", 'SELECT "pg_sleep"(5)', "PG_SLEEP"),  # quoted name
    ("postgres", "SELECT * FROM (SELECT pg_read_file('/etc/passwd')) t", "PG_READ_FILE"),
    # Runs the SQL inside the string, which the parser only sees as text.
    ("postgres", "SELECT query_to_xml('DELETE FROM film RETURNING *', true, false, '')", "QUERY_TO_XML"),
]


@pytest.mark.parametrize(("dialect", "sql", "name"), FORBIDDEN_FUNCTION_CASES)
def test_dangerous_functions_are_rejected(dialect: str, sql: str, name: str) -> None:
    with pytest.raises(UnsafeQueryError, match=f"forbidden function: {name}"):
        validate_sql(sql, dialect=dialect)


@pytest.mark.parametrize("name", sorted(FORBIDDEN_FUNCTIONS))
def test_every_listed_function_is_actually_blocked(name: str) -> None:
    """Guards against a list entry that never matches, e.g. a typo or a
    function sqlglot starts parsing differently in a later version."""
    with pytest.raises(UnsafeQueryError, match="forbidden function"):
        validate_sql(f"SELECT {name}(1)", dialect="postgres")


@pytest.mark.parametrize(
    ("dialect", "sql"),
    [
        ("mysql", "SELECT UPPER(title), COUNT(*), AVG(length) FROM film GROUP BY title"),
        ("mysql", "SELECT COUNT(*) FROM rental WHERE DATEDIFF(return_date, rental_date) > 7"),
        ("mysql", "SELECT COUNT(*) FROM rental WHERE MONTH(rental_date) = 7"),
        ("postgres", "SELECT LOWER(title), NOW(), COALESCE(description, '') FROM film"),
        # The word only appears as text in a string, not as a call.
        ("mysql", "SELECT title FROM film WHERE title = 'SLEEP(5)'"),
    ],
)
def test_ordinary_functions_still_pass(dialect: str, sql: str) -> None:
    assert isinstance(validate_sql(sql, dialect=dialect), exp.Query)


# ---- row limit ----


def limited(sql: str, dialect: str = "mysql", max_rows: int = 1000) -> str:
    """Validate, apply the row limit, and return the SQL that would run."""
    return limit_rows(validate_sql(sql, dialect=dialect), max_rows).sql(dialect=dialect)


@pytest.mark.parametrize(
    ("dialect", "sql", "expected"),
    [
        ("mysql", "SELECT title FROM film", "SELECT title FROM film LIMIT 1000"),
        ("mysql", "SELECT title FROM film LIMIT 5", "SELECT title FROM film LIMIT 5"),
        ("mysql", "SELECT title FROM film LIMIT 5000", "SELECT title FROM film LIMIT 1000"),
        (
            "mysql",
            "SELECT title FROM film ORDER BY title LIMIT 5000",
            "SELECT title FROM film ORDER BY title LIMIT 1000",
        ),
        # MySQL's "LIMIT offset, count" keeps its meaning.
        ("mysql", "SELECT title FROM film LIMIT 10, 5", "SELECT title FROM film LIMIT 5 OFFSET 10"),
        (
            "mysql",
            "SELECT title FROM film LIMIT 5000 OFFSET 20",
            "SELECT title FROM film LIMIT 1000 OFFSET 20",
        ),
        ("mysql", "SELECT 1 UNION SELECT 2", "SELECT 1 UNION SELECT 2 LIMIT 1000"),
        # The inner limit is left alone; only the outer query is capped.
        (
            "mysql",
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
        limited("SELECT title FROM film LIMIT 1+1", dialect="postgres")


def test_original_query_is_not_changed() -> None:
    """The caller may still want to log exactly what the model wrote."""
    tree = validate_sql("SELECT title FROM film LIMIT 5000")
    limit_rows(tree)
    assert tree.sql() == "SELECT title FROM film LIMIT 5000"


# ---- system catalogs and allowed tables ----

ALLOWED = ["film", "actor", "film_actor", "inventory"]


@pytest.mark.parametrize(
    ("dialect", "sql"),
    [
        ("mysql", "SELECT table_name FROM information_schema.tables"),
        ("mysql", "SELECT * FROM mysql.user"),
        ("mysql", "SELECT * FROM performance_schema.threads"),
        ("postgres", "SELECT * FROM pg_catalog.pg_tables"),
        # Postgres finds pg_catalog tables without the prefix.
        ("postgres", "SELECT usename FROM pg_user"),
        ("postgres", "SELECT * FROM film WHERE film_id IN (SELECT 1 FROM pg_roles)"),
    ],
)
def test_system_catalogs_are_always_blocked(dialect: str, sql: str) -> None:
    with pytest.raises(UnsafeQueryError, match="system catalog"):
        validate_sql(sql, dialect=dialect)


@pytest.mark.parametrize(
    ("dialect", "sql"),
    [
        ("mysql", "SELECT * FROM film"),
        ("mysql", "SELECT * FROM sakila.FILM"),  # schema prefix and case ignored
        ("postgres", "SELECT * FROM public.film"),
        ("mysql", "SELECT a.first_name FROM actor a JOIN film_actor fa ON a.actor_id = fa.actor_id"),
        # A CTE name is not a table, so it does not need to be on the list.
        ("mysql", "WITH top AS (SELECT * FROM film) SELECT * FROM top"),
    ],
)
def test_allowed_tables_pass(dialect: str, sql: str) -> None:
    assert isinstance(validate_sql(sql, dialect=dialect, allowed_tables=ALLOWED), exp.Query)


@pytest.mark.parametrize(
    ("sql", "table"),
    [
        ("SELECT * FROM customer", "customer"),
        ("SELECT * FROM film WHERE film_id IN (SELECT film_id FROM payment)", "payment"),
        ("SELECT * FROM film JOIN rental ON 1 = 1", "rental"),
        # Naming a CTE after an allowed table does not hide what it reads.
        ("WITH film AS (SELECT * FROM customer) SELECT * FROM film", "customer"),
    ],
)
def test_tables_not_on_the_list_are_rejected(sql: str, table: str) -> None:
    with pytest.raises(UnsafeQueryError, match=f"not allowed: {table}"):
        validate_sql(sql, allowed_tables=ALLOWED)


def test_no_allowlist_means_any_ordinary_table() -> None:
    assert isinstance(validate_sql("SELECT * FROM customer"), exp.Query)


def test_empty_allowlist_allows_nothing() -> None:
    """An empty list is not the same as no list."""
    with pytest.raises(UnsafeQueryError, match="not allowed: film"):
        validate_sql("SELECT * FROM film", allowed_tables=[])


def test_table_functions_are_not_treated_as_tables() -> None:
    assert isinstance(
        validate_sql("SELECT * FROM generate_series(1, 3)", dialect="postgres", allowed_tables=ALLOWED),
        exp.Query,
    )
