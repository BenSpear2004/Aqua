"""Turn a pipeline Answer into the JSON the frontend reads.

The shape matches what the React app renders (status, message, tables,
visualizations, kpis, error), plus sql so every answer shows the query
that produced it. Database values are converted to plain JSON types
here: Decimal to numbers, dates to ISO strings.

The message comes from summarize.py and the chart from visualize.py: a
single number becomes a KPI card, labels with a measure a bar chart, a
date with a measure a line chart, and anything else just the table.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

from nl2sql.pipeline import Answer
from nl2sql.summarize import summarize
from nl2sql.visualize import suggest_chart

# Column-name words that suggest money. A guess from the name only; the
# frontend shows these as dollars instead of plain numbers.
CURRENCY_WORDS = ("amount", "revenue", "spent", "payment", "price", "cost", "rate", "sales")


def _json_value(value: Any) -> Any:
    """Convert one database value to something JSON can hold."""
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, (dt.date, dt.datetime)):
        return value.isoformat()
    if isinstance(value, (bytes, memoryview)):
        return None  # binary data is not shown
    return value


def _column_type(name: str, values: list[Any]) -> str:
    """Pick the frontend column type: currency, number, date or string."""
    present = [v for v in values if v is not None]
    if present and all(isinstance(v, (dt.date, dt.datetime)) for v in present):
        return "date"
    if present and all(isinstance(v, (int, float, Decimal)) and not isinstance(v, bool) for v in present):
        lowered = name.lower()
        if any(word in lowered for word in CURRENCY_WORDS) and not lowered.endswith("_id"):
            return "currency"
        return "number"
    return "string"


def _unique_keys(columns: list[str]) -> list[str]:
    """Row objects need distinct keys, but SQL allows repeated column names."""
    seen: dict[str, int] = {}
    keys = []
    for name in columns:
        seen[name] = seen.get(name, 0) + 1
        keys.append(name if seen[name] == 1 else f"{name}_{seen[name]}")
    return keys


def _label(key: str) -> str:
    return key.replace("_", " ").strip().capitalize()


def _chart(answer: Answer, keys: list[str], columns: list[dict[str, Any]]) -> tuple[list, list]:
    """The visualizations and kpis lists for one result.

    The frontend draws one x column, so a chart labelled by first and
    last name uses the first of them. Keys come from the table's column
    list, which may have renamed a repeated column name.
    """
    chart = suggest_chart(answer.columns, answer.rows)
    key_of = {name: keys[answer.columns.index(name)] for name in answer.columns}
    if chart.type == "number" and chart.y is not None:
        key = key_of[chart.y]
        column = next(c for c in columns if c["key"] == key)
        kpi = {
            "id": "answer",
            "label": column["label"],
            "value": _json_value(answer.rows[0][answer.columns.index(chart.y)]),
            "type": column["type"],
        }
        return [{"id": "answer-kpi", "type": "kpi", "title": answer.question}], [kpi]
    if chart.type in ("bar", "line") and chart.x and chart.y is not None:
        visualization = {
            "id": "chart",
            "type": chart.type,
            "title": answer.question,
            "tableId": "result",
            "xKey": key_of[chart.x[0]],
            "yKey": key_of[chart.y],
        }
        return [visualization], []
    return [], []


def to_response(answer: Answer) -> dict[str, Any]:
    """Build the JSON reply for one answered (or rejected) question."""
    if answer.error is not None:
        return {
            "status": "error",
            "sql": answer.sql,
            "message": "",
            "tables": [],
            "visualizations": [],
            "kpis": [],
            "error": {"code": answer.error_code, "message": answer.error, "retryable": False},
        }

    keys = _unique_keys(answer.columns)
    columns = []
    for i, key in enumerate(keys):
        column = {"key": key, "label": _label(key), "type": _column_type(key, [row[i] for row in answer.rows])}
        if column["type"] == "currency":
            column["fractionDigits"] = 2  # cents; the frontend defaults to whole dollars
        columns.append(column)
    rows = [{key: _json_value(row[i]) for i, key in enumerate(keys)} for row in answer.rows]
    visualizations, kpis = _chart(answer, keys, columns)
    return {
        "status": "success",
        "sql": answer.sql,
        "message": summarize(answer.columns, answer.rows, answer.truncated),
        "tables": [{"id": "result", "title": answer.question, "columns": columns, "rows": rows}],
        "visualizations": visualizations,
        "kpis": kpis,
        "error": None,
    }


def outage_response(code: str, message: str) -> dict[str, Any]:
    """The body for a server error (model or database unreachable).

    retryable is True because the same question may work once the
    service is back.
    """
    return {
        "status": "error",
        "sql": "",
        "message": "",
        "tables": [],
        "visualizations": [],
        "kpis": [],
        "error": {"code": code, "message": message, "retryable": True},
    }
