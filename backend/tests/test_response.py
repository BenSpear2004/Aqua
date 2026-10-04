"""Tests for nl2sql/response.py: the JSON shape the frontend reads."""

import datetime as dt
import json
from decimal import Decimal

from nl2sql.display import Display
from nl2sql.pipeline import Answer
from nl2sql.response import outage_response, to_response

TOP_KEYS = {
    "status",
    "sql",
    "model",
    "message",
    "tables",
    "visualizations",
    "kpis",
    "error",
}


def answer(columns, rows, **extra) -> Answer:
    return Answer(
        question="Who spent the most?",
        sql="SELECT ...",
        columns=columns,
        rows=rows,
        **extra,
    )


def test_success_shape() -> None:
    body = to_response(
        answer(
            ["first_name", "last_name", "total_spent"],
            [
                ("KARL", "SEAL", Decimal("221.55")),
                ("ELEANOR", "HUNT", Decimal("216.54")),
            ],
        )
    )

    assert set(body) == TOP_KEYS
    assert body["status"] == "success"
    assert body["sql"] == "SELECT ..."
    assert body["error"] is None
    (table,) = body["tables"]
    assert table["title"] == "Who spent the most?"
    assert [c["key"] for c in table["columns"]] == [
        "first_name",
        "last_name",
        "total_spent",
    ]
    assert table["rows"][0] == {
        "first_name": "KARL",
        "last_name": "SEAL",
        "total_spent": 221.55,
    }


def test_whole_body_is_json() -> None:
    """Decimals, dates and timestamps must all be converted."""
    body = to_response(
        answer(
            ["d", "ts", "n", "money"],
            [
                (
                    dt.date(2022, 7, 1),
                    dt.datetime(2022, 7, 1, 12, 30),
                    Decimal("7"),
                    Decimal("2.99"),
                )
            ],
        )
    )
    json.dumps(body)  # raises if anything is left unconverted
    row = body["tables"][0]["rows"][0]
    assert row == {
        "d": "2022-07-01",
        "ts": "2022-07-01T12:30:00",
        "n": 7,
        "money": 2.99,
    }


def test_column_types() -> None:
    body = to_response(
        answer(
            ["title", "rental_count", "total_revenue", "payment_date", "customer_id"],
            [("A", 3, Decimal("9.97"), dt.datetime(2022, 7, 1), 5)],
        )
    )
    types = {c["key"]: c["type"] for c in body["tables"][0]["columns"]}
    assert types == {
        "title": "string",
        "rental_count": "number",
        "total_revenue": "currency",
        "payment_date": "date",
        "customer_id": "string",  # an id names a row; shown as 526, not "526.00" or "5,260"
    }
    revenue = next(
        c for c in body["tables"][0]["columns"] if c["key"] == "total_revenue"
    )
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


def test_messages_come_from_summarize() -> None:
    assert to_response(answer(["n"], []))["message"] == "No matching rows were found."
    assert to_response(answer(["films"], [(1000,)]))["message"] == "**Films**: 1,000."
    truncated = to_response(answer(["title"], [("A",), ("B",)], truncated=True))
    assert truncated["message"].endswith(
        "Only the first 2 rows are shown; there are more."
    )


def test_single_number_becomes_a_kpi_card() -> None:
    body = to_response(answer(["total_revenue"], [(Decimal("67406.56"),)]))
    assert body["kpis"] == [
        {
            "id": "answer",
            "label": "Total revenue",
            "value": 67406.56,
            "type": "currency",
        }
    ]
    assert body["visualizations"] == [
        {"id": "answer-kpi", "type": "kpi", "title": "Who spent the most?"}
    ]


def test_labels_and_a_measure_become_a_bar_chart_on_the_result_table() -> None:
    body = to_response(
        answer(
            ["first_name", "last_name", "total_spent"],
            [
                ("KARL", "SEAL", Decimal("221.55")),
                ("ELEANOR", "HUNT", Decimal("216.54")),
            ],
        )
    )
    (chart,) = body["visualizations"]
    assert chart == {
        "id": "chart",
        "type": "bar",
        "title": "Who spent the most?",
        "tableId": "result",
        "xKey": "first_name",
        "yKey": "total_spent",
    }
    keys = {c["key"] for c in body["tables"][0]["columns"]}
    assert {chart["xKey"], chart["yKey"]} <= keys  # the frontend drops charts that miss
    assert body["kpis"] == []


def test_dates_and_a_measure_become_a_line_chart() -> None:
    body = to_response(
        answer(
            ["day", "rentals"], [(dt.date(2022, 5, 24), 8), (dt.date(2022, 5, 25), 137)]
        )
    )
    assert body["visualizations"][0]["type"] == "line"
    assert body["visualizations"][0]["xKey"] == "day"


def test_chart_keys_follow_renamed_columns() -> None:
    body = to_response(answer(["name", "name", "n"], [("a", "b", 1), ("c", "d", 2)]))
    assert body["visualizations"][0]["xKey"] == "name"
    assert body["visualizations"][0]["yKey"] == "n"


def test_plain_lists_get_no_chart() -> None:
    body = to_response(answer(["title"], [("A",), ("B",)]))
    assert body["visualizations"] == [] and body["kpis"] == []


def test_rejected_answer() -> None:
    body = to_response(
        Answer(
            question="Delete all films rated R.",
            sql="DELETE FROM film WHERE rating = 'R'",
            error="Only SELECT queries are allowed, got DELETE.",
            error_code="rejected",
        )
    )
    assert set(body) == TOP_KEYS
    assert body["status"] == "error"
    assert (
        body["sql"] == "DELETE FROM film WHERE rating = 'R'"
    )  # shown so the user sees what was blocked
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
    assert body["error"] == {
        "code": "model_unavailable",
        "message": "Cannot connect to Ollama.",
        "retryable": True,
    }


def test_the_answering_model_is_reported() -> None:
    """After a fallback the model differs from the one requested; the UI
    shows which one answered."""
    assert to_response(answer(["n"], [(1,)], model="qwen3:8b"))["model"] == "qwen3:8b"
    rejected = Answer(
        question="q",
        sql="DELETE FROM film",
        error="x",
        error_code="rejected",
        model="gemma-4-31b-it",
    )
    assert to_response(rejected)["model"] == "gemma-4-31b-it"
    assert outage_response("model_unavailable", "down")["model"] == ""


# ---- display rules (bank comments) ----

BANK_DISPLAY = Display(
    values_by_column={"status": {"B": "Finished, not paid"}},
    values_anywhere={"VYDAJ": "Debit (money out)"},
    column_labels={"a11": "Average salary"},
    currency="CZK",
)


def test_display_translates_values_labels_and_currency() -> None:
    body = to_response(
        Answer(
            question="q",
            sql="SELECT ...",
            columns=["status", "a11", "balance"],
            rows=[("B", 9000, Decimal("120.50"))],
        ),
        BANK_DISPLAY,
    )
    table = body["tables"][0]
    assert table["rows"][0]["status"] == "Finished, not paid"
    labels = {c["key"]: c["label"] for c in table["columns"]}
    assert labels["a11"] == "Average salary"
    balance = next(c for c in table["columns"] if c["key"] == "balance")
    assert balance["type"] == "currency" and balance["currency"] == "CZK"


def test_summary_uses_the_translated_value() -> None:
    body = to_response(
        Answer(question="q", sql="SELECT ...", columns=["kind"], rows=[("VYDAJ",)]),
        BANK_DISPLAY,
    )
    assert "Debit (money out)" in body["message"]
    assert "VYDAJ" not in body["message"]


def test_money_kpi_carries_the_currency() -> None:
    body = to_response(
        Answer(
            question="q",
            sql="SELECT ...",
            columns=["total_amount"],
            rows=[(Decimal("5000"),)],
        ),
        BANK_DISPLAY,
    )
    assert body["kpis"][0]["currency"] == "CZK"


def test_without_display_nothing_changes() -> None:
    body = to_response(
        Answer(question="q", sql="SELECT ...", columns=["status"], rows=[("B",)])
    )
    assert body["tables"][0]["rows"][0]["status"] == "B"
    assert "currency" not in body["tables"][0]["columns"][0]


def test_header_words_count_for_money() -> None:
    """a11 has no money word in its name, but its header is Average salary."""
    body = to_response(
        Answer(question="q", sql="SELECT ...", columns=["a11"], rows=[(12541,)]),
        BANK_DISPLAY,
    )
    assert body["tables"][0]["columns"][0]["type"] == "currency"
    assert body["kpis"][0]["currency"] == "CZK"


# ---- answer size notes ----


def test_a_full_default_list_says_how_to_see_more() -> None:
    from nl2sql.answer_size import AnswerSize

    rows = [(f"FILM {i}", i) for i in range(10)]
    body = to_response(answer(["title", "rentals"], rows, size=AnswerSize("list", 10)))
    assert body["message"].endswith('Ask for a number, such as "top 25", to see more.')


def test_a_short_default_list_needs_no_note() -> None:
    from nl2sql.answer_size import AnswerSize

    body = to_response(
        answer(["title", "rentals"], [("A", 1), ("B", 2)], size=AnswerSize("list", 10))
    )
    assert "to see more" not in body["message"]


def test_ties_for_first_place_are_explained() -> None:
    from nl2sql.answer_size import AnswerSize

    rows = [("A", 4), ("B", 4), ("C", 4)]
    body = to_response(answer(["title", "rentals"], rows, size=AnswerSize("single")))
    assert body["message"].endswith("3 rows are tied for first place.")


def test_a_single_winner_gets_no_tie_note() -> None:
    from nl2sql.answer_size import AnswerSize

    body = to_response(
        answer(["title", "rentals"], [("A", 34)], size=AnswerSize("single"))
    )
    assert "tied" not in body["message"]


# ---- numbers that are labels ----


def test_years_months_and_ids_are_shown_as_plain_text() -> None:
    body = to_response(
        answer(
            [
                "year",
                "opened_year",
                "month",
                "account_id",
                "account_count",
                "day_count",
            ],
            [(1993, 1993, 7, 1, 1139, 30), (1994, 1994, 8, 2, 439, 31)],
        )
    )
    types = {c["key"]: c["type"] for c in body["tables"][0]["columns"]}
    assert types == {
        "year": "string",
        "opened_year": "string",
        "month": "string",
        "account_id": "string",
        "account_count": "number",  # a count of accounts is a measure
        "day_count": "number",  # a count of days is a measure, not a date part
    }
    # The values stay numbers, so the table still sorts 1993 before 2001.
    assert body["tables"][0]["rows"][0]["year"] == 1993
