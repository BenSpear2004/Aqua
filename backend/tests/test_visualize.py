"""Tests for nl2sql/visualize.py.

The first group uses real results from qwen3:8b questions run against
Pagila on Tiger, with the value types psycopg returns (Decimal for sums
and EXTRACT). The tests at the end pin current behaviour that the module
docstring lists as known limitations; when one is fixed, update its test.
"""

import dataclasses
import datetime as dt
from decimal import Decimal

import pytest

from nl2sql.visualize import MAX_BAR_ROWS, Chart, suggest_chart

# (question, columns, rows, expected type, expected x, expected y)
REAL_RESULTS = [
    ("How many films are there?", ["count"], [(1000,)], "number", (), "count"),
    (
        "What are the 5 most rented films?",
        ["title", "rental_count"],
        [("BUCKET BROTHERHOOD", 34), ("ROCKETEER MOTHER", 33), ("GRIT CLOCKWORK", 32)],
        "bar",
        ("title",),
        "rental_count",
    ),
    (
        "How many rentals were made each month?",
        ["year", "month", "rental_count"],
        [(Decimal(2022), Decimal(2), 182), (Decimal(2022), Decimal(5), 1156), (Decimal(2022), Decimal(6), 2311)],
        "line",
        ("year", "month"),
        "rental_count",
    ),
    (
        "What is the total revenue for each film category?",
        ["name", "total_revenue"],
        [("Sports", Decimal("5314.21")), ("Classics", Decimal("3639.59")), ("New", Decimal("4361.57"))],
        "bar",
        ("name",),
        "total_revenue",
    ),
    (
        "Who are the 5 customers that spent the most money?",
        ["first_name", "last_name", "total_spent"],
        [("KARL", "SEAL", Decimal("221.55")), ("ELEANOR", "HUNT", Decimal("216.54"))],
        "bar",
        ("first_name", "last_name"),
        "total_spent",
    ),
    (
        "Which customers from Canada have rentals that are still not returned?",
        ["customer_id", "first_name", "last_name"],
        [(410, "CURTIS", "IRBY"), (476, "DERRICK", "BOURQUE")],
        "table",
        (),
        None,
    ),
]


@pytest.mark.parametrize(
    ("question", "columns", "rows", "type_", "x", "y"),
    REAL_RESULTS,
    ids=[r[0] for r in REAL_RESULTS],
)
def test_real_results(question, columns, rows, type_, x, y) -> None:
    chart = suggest_chart(columns, rows)
    assert (chart.type, chart.x, chart.y) == (type_, x, y)


# ---- edge cases ----


def test_no_rows_is_a_table() -> None:
    assert suggest_chart(["title"], []).type == "table"


def test_a_real_date_column_gives_a_line() -> None:
    rows = [(dt.date(2022, 5, 1), 1156), (dt.date(2022, 6, 1), 2311)]
    chart = suggest_chart(["month_start", "rentals"], rows)
    assert (chart.type, chart.x, chart.y) == ("line", ("month_start",), "rentals")


def test_id_columns_are_never_the_measure() -> None:
    """film_id is a number but measures nothing, so there is nothing to chart."""
    chart = suggest_chart(["film_id", "title"], [(1, "ACADEMY DINOSAUR"), (2, "ACE GOLDFINGER")])
    assert chart.type == "table"


def test_true_false_columns_are_not_numbers() -> None:
    assert suggest_chart(["active"], [(True,)]).type == "table"


def test_missing_values_do_not_change_the_column_kind() -> None:
    chart = suggest_chart(["name", "total"], [("A", None), ("B", Decimal("2.5"))])
    assert chart.type == "bar"


def test_one_labelled_row_is_a_table() -> None:
    """A bar chart of a single bar says nothing a table doesn't."""
    assert suggest_chart(["title", "rentals"], [("BUCKET BROTHERHOOD", 34)]).type == "table"


def test_too_many_rows_for_a_bar_chart() -> None:
    rows = [(f"film {i}", i) for i in range(MAX_BAR_ROWS + 1)]
    chart = suggest_chart(["title", "rentals"], rows)
    assert chart.type == "table"
    assert str(MAX_BAR_ROWS) in chart.reason


def test_bar_chart_at_the_limit() -> None:
    rows = [(f"film {i}", i) for i in range(MAX_BAR_ROWS)]
    assert suggest_chart(["title", "rentals"], rows).type == "bar"


def test_every_chart_explains_itself() -> None:
    for _, columns, rows, *_ in REAL_RESULTS:
        assert suggest_chart(columns, rows).reason


def test_chart_cannot_be_changed() -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        Chart("bar").type = "line"  # type: ignore[misc]


# ---- known limitations (see the module docstring) ----


def test_limitation_only_the_first_measure_is_charted() -> None:
    chart = suggest_chart(["name", "rentals", "revenue"], [("A", 1, Decimal(2)), ("B", 3, Decimal(4))])
    assert chart.y == "rentals"


def test_limitation_dates_as_text_get_a_bar_chart() -> None:
    """to_char(rental_date, 'YYYY-MM') returns text, so this is a bar, not a line."""
    chart = suggest_chart(["month", "rentals"], [("2022-05", 1156), ("2022-06", 2311)])
    assert chart.type == "bar"
