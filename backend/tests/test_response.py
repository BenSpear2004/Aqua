"""Tests for nl2sql/response.py: the JSON shape the frontend reads."""

import datetime as dt
import json
from decimal import Decimal

from nl2sql.pipeline import Answer
from nl2sql.response import outage_response, to_response

TOP_KEYS = {"status", "sql", "message", "tables", "visualizations", "kpis", "error"}


def answer(columns, rows, **extra) -> Answer:
    return Answer(question="Who spent the most?", sql="SELECT ...", columns=columns, rows=rows, **extra)


def test_success_shape() -> None:
    body = to_response(answer(
        ["first_name", "last_name", "total_spent"],
        [("KARL", "SEAL", Decimal("221.55")), ("ELEANOR", "HUNT", Decimal("216.54"))],
    ))

    assert set(body) == TOP_KEYS
    assert body["status"] == "success"
    assert body["sql"] == "SELECT ..."
    assert body["error"] is None
    (table,) = body["tables"]
    assert table["title"] == "Who spent the most?"
    assert [c["key"] for c in table["columns"]] == ["first_name", "last_name", "total_spent"]
    assert table["rows"][0] == {"first_name": "KARL", "last_name": "SEAL", "total_spent": 221.55}


def test_whole_body_is_json() -> None:
    """Decimals, dates and timestamps must all be converted."""
    body = to_response(answer(
        ["d", "ts", "n", "money"],
        [(dt.date(2022, 7, 1), dt.datetime(2022, 7, 1, 12, 30), Decimal("7"), Decimal("2.99"))],
    ))
    json.dumps(body)  # raises if anything is left unconverted
    row = body["tables"][0]["rows"][0]
    assert row == {"d": "2022-07-01", "ts": "2022-07-01T12:30:00", "n": 7, "money": 2.99}


def test_column_types() -> None:
    body = to_response(answer(
        ["title", "rental_count", "total_revenue", "payment_date", "customer_id"],
        [("A", 3, Decimal("9.97"), dt.datetime(2022, 7, 1), 5)],
    ))
    types = {c["key"]: c["type"] for c in body["tables"][0]["columns"]}
    assert types == {
        "title": "string",
        "rental_count": "number",
        "total_revenue": "currency",
        "payment_date": "date",
        "customer_id": "number",  # an id, even with no money word, is just a number
    }
    revenue = next(c for c in body["tables"][0]["columns"] if c["key"] == "total_revenue")
    assert revenue["fractionDigits"] == 2
    assert revenue["label"] == "Total revenue"


def test_true_false_is_not_a_number() -> None:
    body = to_response(answer(["active"], [(True,), (False,)]))
    assert body["tables"][0]["columns"][0]["type"] == "string"


def test_repeated_column_names_get_distinct_keys() -> None:
    body = to_response(answer(["count", "count"], [(1, 2)]))
    table = body["tables"][0]
    assert [c["key"] for c in table["columns"]] == ["count", "count_2"]
    assert table["rows"][0] == {"count": 1, "count_2": 2}


def test_binary_values_are_not_sent() -> None:
    body = to_response(answer(["picture"], [(b"\x89PNG",)]))
    assert body["tables"][0]["rows"][0]["picture"] is None


def test_messages() -> None:
    assert to_response(answer(["n"], [])) ["message"] == "No matching rows were found."
    assert to_response(answer(["films"], [(1000,)]))["message"] == "The answer is 1000."
    assert to_response(answer(["title"], [("A",), ("B",)]))["message"] == "Found 2 rows."
    truncated = to_response(answer(["title"], [("A",), ("B",)], truncated=True))
    assert truncated["message"] == "Found 2 rows. Only the first 2 are shown."


def test_rejected_answer() -> None:
    body = to_response(Answer(
        question="Delete all films rated R.",
        sql="DELETE FROM film WHERE rating = 'R'",
        error="Only SELECT queries are allowed, got DELETE.",
        error_code="rejected",
    ))
    assert set(body) == TOP_KEYS
    assert body["status"] == "error"
    assert body["sql"] == "DELETE FROM film WHERE rating = 'R'"  # shown so the user sees what was blocked
    assert body["tables"] == []
    assert body["error"] == {
        "code": "rejected",
        "message": "Only SELECT queries are allowed, got DELETE.",
        "retryable": False,
    }


def test_outage_body_is_retryable() -> None:
    body = outage_response("model_unavailable", "Cannot connect to Ollama.")
    assert set(body) == TOP_KEYS
    assert body["status"] == "error"
    assert body["error"] == {"code": "model_unavailable", "message": "Cannot connect to Ollama.", "retryable": True}
