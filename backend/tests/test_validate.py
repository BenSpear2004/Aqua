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

from nl2sql.validate import FORBIDDEN_FUNCTIONS, UnsafeQueryError, validate_sql

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
    ("SHOW TABLES", "Only SELECT queries are allowed"),
    ("EXPLAIN SELECT 1", "Only SELECT queries are allowed"),
    ("GRANT ALL ON *.* TO someone", "got COMMAND"),
    ("REPLACE INTO film (film_id) VALUES (1)", "could not be parsed"),  # MySQL-only syntax
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


# ---- statements that are never allowed (Postgres) ----

NOT_SELECT = "Only SELECT queries are allowed"

# (sql, fragment of the expected error)
POSTGRES_NON_SELECT = [
    # Changing session settings. SET is also how a session would switch
    # off default_transaction_read_only, so it must never get through.
    ("SET statement_timeout = 0", NOT_SELECT),
    ("SET SESSION default_transaction_read_only = off", NOT_SELECT),
    ("RESET ALL", NOT_SELECT),
    ("SET ROLE tsdbadmin", NOT_SELECT),
    # Running procedures or anonymous code blocks.
    ("CALL do_something()", NOT_SELECT),
    ("DO $$ BEGIN DELETE FROM film; END $$", NOT_SELECT),
    # Transaction control.
    ("BEGIN", NOT_SELECT),
    ("START TRANSACTION", NOT_SELECT),
    ("COMMIT", NOT_SELECT),
    ("ROLLBACK", NOT_SELECT),
    ("SAVEPOINT s1", NOT_SELECT),
    ("BEGIN; SELECT 1", "exactly one statement"),
    # Writes hidden inside a WITH clause (data-modifying CTEs).
    ("WITH d AS (DELETE FROM film WHERE film_id = 1 RETURNING *) SELECT * FROM d", "forbidden operation: DELETE"),
    ("WITH u AS (UPDATE film SET title = 'x' RETURNING *) SELECT * FROM u", "forbidden operation: UPDATE"),
    (
        "WITH i AS (INSERT INTO actor (first_name, last_name) VALUES ('a', 'b') RETURNING *) SELECT * FROM i",
        "forbidden operation: INSERT",
    ),
    # Moving data in or out, locking, and maintenance.
    ("COPY film TO STDOUT", NOT_SELECT),
    ("COPY (SELECT * FROM film) TO '/tmp/f'", NOT_SELECT),
    ("LOCK TABLE film", NOT_SELECT),
    ("VACUUM film", NOT_SELECT),
    ("ANALYZE film", NOT_SELECT),
    # Messaging, prepared statements and cursors.
    ("LISTEN chan", NOT_SELECT),
    ("NOTIFY chan, 'hi'", "could not be parsed"),
    ("PREPARE p AS SELECT 1", NOT_SELECT),
    ("EXECUTE p", NOT_SELECT),
    ("DECLARE c CURSOR FOR SELECT * FROM film", NOT_SELECT),
    # EXPLAIN ANALYZE actually runs the statement it explains.
    ("EXPLAIN ANALYZE DELETE FROM film", NOT_SELECT),
    # Shorthand forms of SELECT. Rejected to keep the rule simple.
    ("TABLE film", NOT_SELECT),
    ("VALUES (1), (2)", NOT_SELECT),
]


@pytest.mark.parametrize(("sql", "reason"), POSTGRES_NON_SELECT)
def test_postgres_non_select_statements_are_rejected(sql: str, reason: str) -> None:
    with pytest.raises(UnsafeQueryError, match=reason):
        validate_sql(sql, dialect="postgres")


def test_read_only_cte_still_passes_in_postgres() -> None:
    """The WITH rejections above are about writes, not WITH itself."""
    sql = "WITH x AS (SELECT * FROM film) SELECT * FROM x"
    assert isinstance(validate_sql(sql, dialect="postgres"), exp.Query)


# ---- Postgres is the default ----


def test_default_dialect_is_postgres() -> None:
    """Backtick quoting is MySQL syntax, so it only parses when the
    validator is reading MySQL. With no dialect given it must not."""
    with pytest.raises(UnsafeQueryError, match="could not be parsed"):
        validate_sql("SELECT `title` FROM film")
    assert isinstance(validate_sql("SELECT `title` FROM film", dialect="mysql"), exp.Query)


# Extension schemas on our Tiger Cloud database (TimescaleDB and its
# toolkit). Internal bookkeeping, never Pagila data.
TIMESCALE_SCHEMAS = [
    "_timescaledb_cache",
    "_timescaledb_catalog",
    "_timescaledb_config",
    "_timescaledb_functions",
    "_timescaledb_internal",
    "timescale_functions",
    "timescaledb_experimental",
    "timescaledb_information",
    "toolkit_experimental",
]


@pytest.mark.parametrize("schema", TIMESCALE_SCHEMAS)
def test_timescaledb_schemas_are_blocked(schema: str) -> None:
    with pytest.raises(UnsafeQueryError, match="system catalog"):
        validate_sql(f"SELECT * FROM {schema}.hypertable")


# ---- hidden columns (Phase 5) ----

# staff is allowed, but its password hash and picture never are. The
# database also refuses them (db/05_hide_columns.sql); this is layer 1.
WITH_STAFF = ["staff", "rental", "payment", "film"]

HIDDEN_COLUMN_ATTACKS = [
    ("SELECT password FROM staff", "hidden column: password"),
    ("SELECT s.password FROM staff s", "hidden column: password"),
    ('SELECT "PASSWORD" FROM staff', "hidden column: password"),
    # Guessing the hash one character at a time never shows the column.
    ("SELECT username FROM staff WHERE password LIKE 'a%'", "hidden column: password"),
    ("SELECT username FROM staff ORDER BY password", "hidden column: password"),
    ("SELECT md5(picture::text) FROM staff", "hidden column: picture"),
    # A star would include the hidden columns.
    ("SELECT * FROM staff", "named columns from staff"),
    ("SELECT s.* FROM staff s", "named columns from staff"),
    ("SELECT * FROM (SELECT * FROM staff) t", "named columns from staff"),
    ("SELECT t.* FROM rental r JOIN staff t ON r.staff_id = t.staff_id", "named columns from staff"),
    ("WITH x AS (SELECT * FROM staff) SELECT first_name FROM x", "named columns from staff"),
    # The whole row as one value also includes them.
    ("SELECT row_to_json(s) FROM staff s", "whole staff row"),
    ("SELECT to_jsonb(staff) FROM staff", "whole staff row"),
    ("SELECT s FROM staff s", "whole staff row"),
]


@pytest.mark.parametrize(("sql", "reason"), HIDDEN_COLUMN_ATTACKS)
def test_hidden_staff_columns_are_rejected(sql: str, reason: str) -> None:
    with pytest.raises(UnsafeQueryError, match=reason):
        validate_sql(sql, allowed_tables=WITH_STAFF)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT first_name, last_name, email FROM staff",
        "SELECT count(*) FROM staff",  # a star inside COUNT is not a column list
        "SELECT s.first_name, count(*) AS n FROM staff s JOIN payment p ON p.staff_id = s.staff_id GROUP BY s.first_name",
        "SELECT * FROM film",  # stars are fine when staff is not involved
        "SELECT title FROM film WHERE title = 'password'",  # the word as data
    ],
)
def test_ordinary_staff_queries_pass(sql: str) -> None:
    assert isinstance(validate_sql(sql, allowed_tables=WITH_STAFF), exp.Query)


# ---- the app's own tables (Phase 5) ----


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT question, sql FROM retrieval.example_query",
        "SELECT * FROM retrieval.schema_doc",
        "SELECT title FROM film WHERE title IN (SELECT question FROM retrieval.example_query)",
    ],
)
def test_retrieval_schema_is_always_blocked(sql: str) -> None:
    """Blocked even without an allowlist, like the system catalogs."""
    with pytest.raises(UnsafeQueryError, match="internal tables"):
        validate_sql(sql)


# ---- more dangerous Postgres functions (Phase 5) ----


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT pg_notify('chan', 'hi')",  # sends a message to other sessions
        "SELECT nextval('film_film_id_seq')",  # changes a sequence
        "SELECT setval('film_film_id_seq', 1)",
        "SELECT lo_get(1234)",  # reads a large object
        "SELECT pg_ls_logdir()",
        "SELECT pg_try_advisory_lock(1)",
        "SELECT postgres_fdw_get_connections()",
        "SELECT dblink_connect('host=evil')",
    ],
)
def test_more_postgres_functions_are_rejected(sql: str) -> None:
    with pytest.raises(UnsafeQueryError, match="forbidden function"):
        validate_sql(sql)


# ---- which rejections the model may retry (Phase 5) ----


@pytest.mark.parametrize(
    ("sql", "fixable"),
    [
        ("SELEC title FROM film", True),  # a typo the model can correct
        ("SELECT * FROM customer", True),  # a table it should not use
        ("SELECT password FROM staff", True),  # it can name other columns
        ("DELETE FROM film", False),  # the question asked for a write
        ("SELECT pg_sleep(5)", False),
        ("SELECT * FROM pg_user", False),
    ],
)
def test_rejections_say_whether_a_retry_could_help(sql: str, fixable: bool) -> None:
    with pytest.raises(UnsafeQueryError) as caught:
        validate_sql(sql, allowed_tables=WITH_STAFF)
    assert caught.value.fixable is fixable


def test_rejections_are_not_fixable_by_default() -> None:
    assert UnsafeQueryError("x").fixable is False
