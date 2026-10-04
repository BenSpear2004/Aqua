"""Turn result rows into a short readable answer.

Built from the rows with fixed rules, not by the model: the summary then
can never state a number the query did not return, costs no extra model
call (reasoning answers already take seconds), and is easy to test. The
table, chart and SQL sit right below it, so it only needs to lead.

Returns Markdown; the frontend renders it without raw HTML.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from decimal import Decimal
from typing import Any

# How many leading rows a multi-row summary names.
NAMED_ROWS = 3


def _label(column: str) -> str:
    return column.replace("_", " ").strip().capitalize()


def format_value(value: Any) -> str:
    """A value as a person would write it: 1,000 and 67,406.56."""
    if value is None:
        return "none"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, Decimal):
        if value == value.to_integral_value():
            return f"{int(value):,}"
        return f"{value:,.2f}"
    if isinstance(value, int):
        return f"{value:,}"
    if isinstance(value, float):
        return f"{value:,.2f}"
    if isinstance(value, dt.datetime):
        return value.strftime("%Y-%m-%d %H:%M")
    if isinstance(value, dt.date):
        return value.isoformat()
    if isinstance(value, (bytes, memoryview)):
        return "(binary)"
    return str(value).strip()


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float, Decimal)) and not isinstance(value, bool)


def _join(items: list[str]) -> str:
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def _row_label(columns: Sequence[str], row: Sequence[Any]) -> tuple[str, str | None]:
    """Split a row into its text label and its first measure, if any."""
    texts = [format_value(v) for c, v in zip(columns, row) if isinstance(v, str)]
    numbers = [
        format_value(v)
        for c, v in zip(columns, row)
        if _is_number(v) and not c.lower().endswith("_id") and c.lower() != "id"
    ]
    return " ".join(texts[:2]), (numbers[0] if numbers else None)


def summarize(
    columns: Sequence[str], rows: Sequence[Sequence[Any]], truncated: bool = False
) -> str:
    """One or two sentences describing what the query returned."""
    count = len(rows)
    if count == 0:
        return "No matching rows were found."

    if count == 1:
        pairs = [
            f"**{_label(c)}**: {format_value(v)}" for c, v in zip(columns, rows[0])
        ]
        if len(pairs) == 1:
            return pairs[0] + "."
        return "; ".join(pairs) + "."

    text = f"Found {count:,} rows"
    named = []
    for row in rows[:NAMED_ROWS]:
        label, measure = _row_label(columns, row)
        if label:
            named.append(f"{label} ({measure})" if measure is not None else label)
    if named:
        text += f". The first {'are' if len(named) > 1 else 'is'} {_join(named)}"
    text += "."
    if truncated:
        text += f" Only the first {count:,} rows are shown; there are more."
    return text
