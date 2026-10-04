"""Tests for eval/metrics.py: when a predicted result counts as correct."""

import datetime as dt
from decimal import Decimal

import pytest

from eval.metrics import exact_match, lenient_match, normalize, summarize_run

NAMES = [("KARL", "SEAL"), ("ELEANOR", "HUNT")]


def test_same_rows_in_another_order_match_when_order_does_not_matter() -> None:
    assert exact_match(NAMES, list(reversed(NAMES)), ordered=False)


def test_order_matters_for_ranked_questions() -> None:
    assert exact_match(NAMES, NAMES, ordered=True)
    assert not exact_match(NAMES, list(reversed(NAMES)), ordered=True)


def test_column_order_does_not_matter() -> None:
    assert exact_match(
        [("Sports", Decimal("5314.21"))], [(5314.21, "Sports")], ordered=False
    )


def test_rounding_and_padding_are_ignored() -> None:
    assert exact_match([(Decimal("216.540"),)], [(216.54,)], ordered=False)
    assert exact_match([("English",)], [("English             ",)], ordered=False)
    assert exact_match([(Decimal("115.272"),)], [(Decimal("115.27"),)], ordered=False)


def test_different_values_or_counts_do_not_match() -> None:
    assert not exact_match([(1000,)], [(999,)], ordered=False)
    assert not exact_match(NAMES, NAMES[:1], ordered=False)
    assert not exact_match(
        [(1,), (1,)], [(1,), (2,)], ordered=False
    )  # duplicates count


def test_extra_columns_fail_exact_but_pass_lenient() -> None:
    pred = [("KARL", "SEAL", Decimal("221.55")), ("ELEANOR", "HUNT", Decimal("216.54"))]
    assert not exact_match(NAMES, pred, ordered=False)
    assert lenient_match(NAMES, pred, ordered=False)


def test_lenient_still_needs_the_right_rows_and_order() -> None:
    pred = [("ELEANOR", "HUNT", 216.54), ("KARL", "SEAL", 221.55)]
    assert not lenient_match(NAMES, pred, ordered=True)
    assert not lenient_match(NAMES, [("KARL", "SEAL", 1)], ordered=False)


def test_lenient_does_not_mix_values_across_columns() -> None:
    """Gold columns must map to whole prediction columns, row by row."""
    gold = [("a", "x"), ("b", "y")]
    assert not lenient_match(gold, [("a", "y", 0), ("b", "x", 0)], ordered=False)


def test_empty_results() -> None:
    assert exact_match([], [], ordered=False)
    assert not lenient_match([], [("x",)], ordered=False)


@pytest.mark.parametrize(
    ("value", "normal"),
    [
        (Decimal("7.00"), 7),
        (2.999, 3),
        (True, True),
        (dt.date(2022, 7, 1), "2022-07-01"),
        (None, None),
    ],
)
def test_normalize(value, normal) -> None:
    assert normalize(value) == normal


def test_summary_counts_accuracy_and_failure_kinds() -> None:
    records = [
        {
            "difficulty": "easy",
            "status": "ok",
            "exact": True,
            "lenient": True,
            "seconds": 2.0,
        },
        {
            "difficulty": "easy",
            "status": "ok",
            "exact": False,
            "lenient": True,
            "seconds": 4.0,
            "attempts": 2,
        },
        {
            "difficulty": "hard",
            "status": "rejected",
            "exact": False,
            "lenient": False,
            "seconds": 3.0,
        },
        {
            "difficulty": "hard",
            "status": "outage",
            "exact": False,
            "lenient": False,
            "seconds": None,
        },
    ]
    summary = summarize_run(records)
    assert summary["n"] == 4
    assert summary["execution_accuracy_exact"] == 0.25
    assert summary["execution_accuracy_lenient"] == 0.5
    assert summary["validity_rate"] == 0.5
    assert (summary["rejected"], summary["outage"], summary["retried"]) == (1, 1, 1)
    assert summary["median_seconds"] == 3.0
    assert summary["by_difficulty"]["easy"] == {"n": 2, "exact": 0.5, "lenient": 1.0}
