"""Pick a chart for a query result.

The backend decides which chart fits the rows; the frontend draws it.
Rules look only at the shape of the result (how many rows, and which
columns hold numbers, dates or text), so the choice is predictable,
instant and testable, with no model call. Anything that does not fit a
rule falls back to a plain table.

This is a first version for Ben to take over. Known limitations:

- Only one measure is charted. A result with two number columns (for
  example rentals and revenue) uses the first and ignores the second.
- Only bar, line, big number and table. No pie, stacked or grouped bars.
- At most two text columns are used as labels; others are ignored.
- Time is recognised from real date columns, or from number columns
  named year, quarter, month, week, day or hour. Dates returned as text
  (for example to_char output, or month names like "Jan") are treated as
  labels, so they get a bar chart instead of a line.
- Rows are not sorted. The frontend should sort bars biggest first when
  the SQL had no ORDER BY, and sort line points by time.
- A truncated result (more rows than the limit) is charted without a
  warning; the frontend should show that only part of the data is drawn.
- The question itself is ignored. "What share of revenue..." could suit
  a pie chart, but only the result's shape is used.
- MAX_BAR_ROWS = 25 is a guess, not a tested value.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

# A bar chart with more bars than this is hard to read; show a table.
MAX_BAR_ROWS = 25

# Models often split dates into number columns, e.g.
# EXTRACT(YEAR ...) AS year, EXTRACT(MONTH ...) AS month. Number columns
# with these names are treated as points in time, not as measurements.
TIME_PART_NAMES = frozenset({"year", "quarter", "month", "week", "day", "hour"})


@dataclass(frozen=True)
class Chart:
    """How the frontend should draw a result.

    type is "number", "bar", "line" or "table". For bar and line, x names
    the label columns (joined with a space, e.g. first and last name) and
    y names the column whose values set the bar height or line position.
    reason says which rule matched, for debugging and for the demo.
    """

    type: str
    x: tuple[str, ...] = field(default=())
    y: str | None = None
    reason: str = ""


def _kind(values: list[Any]) -> str:
    """Classify a column as "number", "time", "text" or "other"."""
    present = [v for v in values if v is not None]
    if not present:
        return "other"
    if all(isinstance(v, bool) for v in present):
        return "other"  # bool is a subclass of int; don't chart it as a number
    if all(isinstance(v, (int, float, Decimal)) for v in present):
        return "number"
    if all(isinstance(v, (dt.date, dt.datetime)) for v in present):
        return "time"
    if all(isinstance(v, str) for v in present):
        return "text"
    return "other"


def _is_id(column: str) -> bool:
    """IDs are numbers but measure nothing, so never use them as y."""
    name = column.lower()
    return name == "id" or name.endswith("_id")


def suggest_chart(columns: Sequence[str], rows: Sequence[Sequence[Any]]) -> Chart:
    """Choose a chart from the columns and rows a query returned."""
    if not rows:
        return Chart("table", reason="no rows")

    kinds = {col: _kind([row[i] for row in rows]) for i, col in enumerate(columns)}
    time_parts = [c for c in columns if kinds[c] == "number" and c.lower() in TIME_PART_NAMES]
    numbers = [c for c in columns if kinds[c] == "number" and not _is_id(c) and c not in time_parts]
    times = [c for c in columns if kinds[c] == "time"]
    texts = [c for c in columns if kinds[c] == "text"]

    if len(rows) == 1 and len(columns) == 1 and numbers:
        return Chart("number", y=numbers[0], reason="a single number")
    if len(times) == 1 and numbers and len(rows) >= 2:
        return Chart("line", x=(times[0],), y=numbers[0], reason="a date column and a number column")
    if time_parts and numbers and len(rows) >= 2:
        return Chart("line", x=tuple(time_parts), y=numbers[0], reason="year/month columns and a number column")
    if texts and numbers and 2 <= len(rows) <= MAX_BAR_ROWS:
        return Chart("bar", x=tuple(texts[:2]), y=numbers[0], reason="text labels and a number column")
    if texts and numbers and len(rows) > MAX_BAR_ROWS:
        return Chart("table", reason=f"more than {MAX_BAR_ROWS} rows for a bar chart")
    return Chart("table", reason="no column to measure")
