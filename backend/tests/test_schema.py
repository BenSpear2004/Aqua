"""Tests for nl2sql/schema.py.

The first group builds a Schema by hand, so it needs no database. The
last group reads the real database through DATABASE_URL and is skipped
when that is not set.
"""

import pytest

from nl2sql.config import load_settings
from nl2sql.db import connect
from nl2sql.schema import HIDDEN_COLUMNS, Column, Schema, Table, load_schema

FILM = Table(
    name="film",
    columns=(
        Column("film_id", "integer", True),
        Column("title", "text", True),
        Column("rating", "mpaa_rating", False),
        Column("release_year", "year", False),
    ),
    constraints=("PRIMARY KEY (film_id)",),
    references=frozenset(),
)
CATEGORY = Table(
    name="category",
    columns=(
        Column("category_id", "integer", True),
        Column("name", "text", True, values=("Action", "Comedy")),
    ),
    constraints=("PRIMARY KEY (category_id)",),
    references=frozenset(),
)
FILM_CATEGORY = Table(
    name="film_category",
    columns=(
        Column("film_id", "integer", True),
        Column("category_id", "integer", True),
    ),
    constraints=(
        "PRIMARY KEY (film_id, category_id)",
        "FOREIGN KEY (film_id) REFERENCES film(film_id)",
        "FOREIGN KEY (category_id) REFERENCES category(category_id)",
    ),
    references=frozenset({"film", "category"}),
)
# No foreign keys, like Pagila's partitioned payment table; the join to
# customer is only implied by the column name.
PAYMENT = Table(
    name="payment",
    columns=(
        Column("payment_id", "integer", True),
        Column("customer_id", "integer", True),
    ),
    constraints=("PRIMARY KEY (payment_id)",),
    references=frozenset(),
)
CUSTOMER = Table(
    name="customer",
    columns=(
        Column("customer_id", "integer", True),
        Column("first_name", "text", True),
    ),
    constraints=("PRIMARY KEY (customer_id)",),
    references=frozenset(),
)

SCHEMA = Schema(
    tables={t.name: t for t in (FILM, CATEGORY, FILM_CATEGORY, PAYMENT, CUSTOMER)},
    enums={"mpaa_rating": ("G", "PG", "R"), "unused_enum": ("x",)},
    domains={"year": "integer"},
)


def test_allowed_tables_are_exactly_the_tables() -> None:
    assert SCHEMA.allowed_tables == {
        "film",
        "category",
        "film_category",
        "payment",
        "customer",
    }


def test_prompt_is_create_statements_with_used_types_first() -> None:
    prompt = SCHEMA.to_prompt(["film"])
    assert prompt.startswith("CREATE TYPE mpaa_rating AS ENUM ('G', 'PG', 'R');")
    assert "CREATE DOMAIN year AS integer;" in prompt
    assert "unused_enum" not in prompt  # no table in the prompt uses it
    assert (
        "CREATE TABLE film (\n  film_id integer NOT NULL,\n  title text NOT NULL,"
        in prompt
    )
    assert prompt.endswith("  PRIMARY KEY (film_id)\n);")
    assert "category" not in prompt


def test_prompt_lists_values_after_the_comma() -> None:
    prompt = SCHEMA.to_prompt(["category"])
    assert "  name text NOT NULL,  -- values: Action, Comedy" in prompt


def test_prompt_for_all_tables_is_sorted_and_ignores_unknown_names() -> None:
    full = SCHEMA.to_prompt()
    assert full.index("CREATE TABLE category") < full.index("CREATE TABLE film (")
    assert SCHEMA.to_prompt(["FILM", "no_such_table"]) == SCHEMA.to_prompt(["film"])


def test_related_follows_foreign_keys_both_ways() -> None:
    assert SCHEMA.related(["film_category"]) == {"film_category", "film", "category"}
    assert SCHEMA.related(["category"]) == {"category", "film_category"}


def test_related_follows_id_column_names_without_foreign_keys() -> None:
    assert SCHEMA.related(["payment"]) == {"payment", "customer"}
    assert SCHEMA.related(["customer"]) == {"customer", "payment"}


def test_related_ignores_unknown_tables() -> None:
    assert SCHEMA.related(["nope"]) == set()


def test_describe_is_plain_text_for_embedding() -> None:
    text = SCHEMA.describe("category")
    assert text.startswith("Table category (category). Columns: category id, name.")
    assert "Joins to: film_category." in text
    assert "name values: Action, Comedy." in text


def test_quotes_in_enum_labels_are_escaped() -> None:
    schema = Schema(tables={"film": FILM}, enums={"mpaa_rating": ("it's",)})
    assert "('it''s')" in schema.to_prompt()


# ---- against the real database ----

SETTINGS = load_settings()
needs_db = pytest.mark.skipif(
    not SETTINGS.database_url, reason="DATABASE_URL is not set"
)


@pytest.fixture(scope="module")
def pagila() -> Schema:
    with connect(SETTINGS) as conn:
        return load_schema(conn)


@needs_db
def test_real_schema_has_the_pagila_tables_without_partitions(pagila: Schema) -> None:
    assert len(pagila.tables) == 15
    assert {"film", "payment", "rental", "staff"} <= pagila.allowed_tables
    assert not any(name.startswith("payment_p") for name in pagila.tables)


@needs_db
def test_real_schema_hides_staff_secrets(pagila: Schema) -> None:
    staff_columns = {c.name for c in pagila.tables["staff"].columns}
    for _, column in HIDDEN_COLUMNS:
        assert column not in staff_columns
    assert "password" not in pagila.to_prompt()


@needs_db
def test_real_schema_has_types_keys_and_values(pagila: Schema) -> None:
    prompt = pagila.to_prompt()
    assert (
        "CREATE TYPE mpaa_rating AS ENUM ('G', 'PG', 'PG-13', 'R', 'NC-17');" in prompt
    )
    assert "FOREIGN KEY (city_id) REFERENCES city(city_id)" in prompt
    assert "ON UPDATE" not in prompt  # write-only detail, trimmed
    names = {c.name: c for c in pagila.tables["category"].columns}["name"].values
    assert "Horror" in names
    # Too many distinct titles to list, and arrays are never listed.
    film = {c.name: c for c in pagila.tables["film"].columns}
    assert film["title"].values == () and film["special_features"].values == ()


@needs_db
def test_real_schema_never_lists_personal_values(pagila: Schema) -> None:
    for table in pagila.tables.values():
        for column in table.columns:
            if any(
                word in column.name for word in ("email", "phone", "address", "user")
            ):
                assert column.values == ()


@needs_db
def test_real_payment_joins_by_column_names(pagila: Schema) -> None:
    assert pagila.related(["payment"]) >= {"customer", "rental", "staff"}


# ---- comments ----


def test_prompt_shows_table_and_column_comments() -> None:
    """The bank's codes (PRIJEM, loan status B) mean nothing to the model
    without the database comments that explain them."""
    loan = Table(
        name="loan",
        columns=(
            Column("duration", "integer", True, comment="Loan length in months."),
            Column("status", "text", True, values=("A", "B"), comment="A = paid off; B = not paid."),
            Column("amount", "integer", True),
        ),
        constraints=("PRIMARY KEY (loan_id)",),
        references=frozenset(),
        comment="Loans granted to accounts.",
    )
    prompt = Schema(tables={"loan": loan}).to_prompt()

    assert prompt.startswith("-- Loans granted to accounts.\nCREATE TABLE loan (")
    assert "  duration integer NOT NULL,  -- Loan length in months." in prompt
    assert "  status text NOT NULL,  -- A = paid off; B = not paid. Values: A, B" in prompt
    assert "  amount integer NOT NULL,\n" in prompt  # no comment, no marker


def test_tables_without_comments_look_as_before() -> None:
    assert not SCHEMA.to_prompt().startswith("--")
    assert "-- values: " in SCHEMA.to_prompt()


def test_comments_are_kept_on_one_line() -> None:
    from nl2sql.schema import _one_line

    assert _one_line("Line one.\n  Line two.") == "Line one. Line two."
    assert _one_line(None) == ""


def test_reserved_table_names_are_quoted_in_the_prompt() -> None:
    """order is a reserved word: FROM order is a syntax error."""
    order = Table(
        name="order",
        columns=(Column("order_id", "integer", True),),
        constraints=(),
        references=frozenset(),
        quoted_name='"order"',
    )
    assert 'CREATE TABLE "order" (' in Schema(tables={"order": order}).to_prompt()
    assert Schema(tables={"order": order}).allowed_tables == frozenset({"order"})


def test_blank_values_are_shown_quoted() -> None:
    from nl2sql.schema import _display_value

    assert _display_value(" ") == "' '"
    assert _display_value("") == "''"
    assert _display_value("English             ") == "English"  # padding still trimmed
