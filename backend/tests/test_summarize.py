"""Tests for nl2sql/summarize.py. Plain data in, text out; no model."""

import datetime as dt
from decimal import Decimal

import pytest

from nl2sql.summarize import format_value, summarize


def test_no_rows() -> None:
    assert summarize(["n"], []) == "No matching rows were found."


def test_single_value_names_the_column() -> None:
    assert summarize(["film_count"], [(1000,)]) == "**Film count**: 1,000."
    assert (
        summarize(["total_revenue"], [(Decimal("67406.56"),)])
        == "**Total revenue**: 67,406.56."
    )


def test_single_row_lists_every_column() -> None:
    text = summarize(
        ["first_name", "last_name", "total_spent"],
        [("KARL", "SEAL", Decimal("221.55"))],
    )
    assert text == "**First name**: KARL; **Last name**: SEAL; **Total spent**: 221.55."


def test_many_rows_name_the_first_few_with_their_measure() -> None:
    rows = [
        ("Sports", Decimal("5314.21")),
        ("Sci-Fi", Decimal("4756.98")),
        ("Animation", Decimal("4656.30")),
        ("Drama", Decimal("4587.39")),
    ]
    text = summarize(["category", "total_sales"], rows)
    assert (
        text
        == "Found 4 rows. The first are Sports (5,314.21), Sci-Fi (4,756.98) and Animation (4,656.30)."
    )


def test_two_text_columns_make_one_label_and_ids_are_not_measures() -> None:
    rows = [(148, "ELEANOR", "HUNT", 46), (526, "KARL", "SEAL", 45)]
    text = summarize(["customer_id", "first_name", "last_name", "rentals"], rows)
    assert text == "Found 2 rows. The first are ELEANOR HUNT (46) and KARL SEAL (45)."


def test_rows_without_text_just_count() -> None:
    assert summarize(["year", "n"], [(2022, 5), (2023, 6)]) == "Found 2 rows."


def test_truncated_results_say_so() -> None:
    text = summarize(["title"], [("A",), ("B",)], truncated=True)
    assert text.endswith("Only the first 2 rows are shown; there are more.")


@pytest.mark.parametrize(
    ("value", "shown"),
    [
        (None, "none"),
        (True, "yes"),
        (Decimal("7"), "7"),
        (Decimal("2.5"), "2.50"),
        (1234567, "1,234,567"),
        (0.125, "0.12"),
        (dt.date(2022, 7, 1), "2022-07-01"),
        (dt.datetime(2022, 7, 1, 9, 5, 30), "2022-07-01 09:05"),
        ("English             ", "English"),  # character(20) padding
        (b"\x89PNG", "(binary)"),
    ],
)
def test_format_value(value, shown: str) -> None:
    assert format_value(value) == shown
