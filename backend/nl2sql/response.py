"""Turn a pipeline Answer into the JSON the frontend reads.

The shape matches what the React app renders (status, message, tables,
visualizations, kpis, error), plus sql so every answer shows the query
that produced it. Database values are converted to plain JSON types
here: Decimal to numbers, dates to ISO strings.

Charts and KPI cards stay empty until visualize.py is wired in, and the
message is a plain one-line description until summarize.py exists.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

from nl2sql.pipeline import Answer

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


def _message(answer: Answer) -> str:
    """A plain description of the result until summarize.py exists."""
    count = len(answer.rows)
    if count == 0:
        return "No matching rows were found."
    if count == 1 and len(answer.columns) == 1:
        return f"The answer is {_json_value(answer.rows[0][0])}."
    text = f"Found {count} row{'s' if count != 1 else ''}."
    if answer.truncated:
        text += f" Only the first {count} are shown."
    return text


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
    rows =[{key: _json_value(row[i]) for i, key in enumerate(keys)} for row in answer.rows]
    return {
        "status": "success",
        "sql": answer.sql,
        "message": _message(answer),
        "tables": [{"id": "result", "title": answer.question, "columns": columns, "rows": rows}],
        "visualizations": [],
        "kpis": [],
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
