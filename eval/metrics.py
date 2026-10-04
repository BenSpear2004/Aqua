"""Decide whether a predicted result matches the gold result, and add up
the scores for a run.

Execution accuracy compares what the queries return, not the SQL text,
because many different queries are correct. Two levels:

- exact: same rows, each row with the same values in any column order.
- lenient: the prediction holds every gold column, in the same rows,
  plus possibly extra columns. A model that answers "which customers
  paid over $200" with names AND totals has answered correctly.

Rows are compared as a multiset unless the question asks for an order
("top 3"), in which case the order must match too. Numbers are rounded
to 2 places so 216.540 and 216.54 agree; text is trimmed because
character(20) columns are padded.
"""

from __future__ import annotations

import datetime as dt
import itertools
from collections import Counter
from collections.abc import Iterable, Sequence
from decimal import Decimal
from typing import Any

# Prediction columns tried when looking for the gold columns inside a
# wider result. Bounds the permutations; real results are narrower.
MAX_COLUMNS_SEARCHED = 8


def normalize(value: Any) -> Any:
    """One comparable form per value, whatever type the driver returned."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float, Decimal)):
        rounded = round(float(value), 2)
        return int(rounded) if rounded == int(rounded) else rounded
    if isinstance(value, (dt.date, dt.datetime)):
        return value.isoformat()
    return str(value).strip()


def _row_key(row: Sequence[Any]) -> tuple:
    """A row as a column-order-free key: its sorted normalized values."""
    return tuple(sorted((repr(normalize(v)) for v in row)))


def exact_match(
    gold: Sequence[Sequence[Any]], pred: Sequence[Sequence[Any]], ordered: bool
) -> bool:
    if len(gold) != len(pred):
        return False
    if gold and len(gold[0]) != len(pred[0]):
        return False
    gold_keys = [_row_key(r) for r in gold]
    pred_keys = [_row_key(r) for r in pred]
    if ordered:
        return gold_keys == pred_keys
    return Counter(gold_keys) == Counter(pred_keys)


def _project(rows: Sequence[Sequence[Any]], columns: Sequence[int]) -> list[tuple]:
    return [tuple(normalize(row[i]) for i in columns) for row in rows]


def lenient_match(
    gold: Sequence[Sequence[Any]], pred: Sequence[Sequence[Any]], ordered: bool
) -> bool:
    """True if some choice of prediction columns reproduces the gold rows."""
    if exact_match(gold, pred, ordered):
        return True
    if len(gold) != len(pred) or not gold:
        return False
    width_gold, width_pred = len(gold[0]), len(pred[0])
    if width_pred < width_gold or width_pred > MAX_COLUMNS_SEARCHED:
        return False
    target = [tuple(normalize(v) for v in row) for row in gold]
    for columns in itertools.permutations(range(width_pred), width_gold):
        projected = _project(pred, columns)
        if projected == target if ordered else Counter(projected) == Counter(target):
            return True
    return False


def summarize_run(records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Totals for a run: accuracy overall and by difficulty, plus the
    rates that explain failures (rejected, failed, unreachable)."""
    records = list(records)
    total = len(records)

    def rate(items: list[dict], key: str) -> float:
        return round(sum(1 for r in items if r[key]) / len(items), 3) if items else 0.0

    by_difficulty = {}
    for level in ("easy", "medium", "hard"):
        items = [r for r in records if r.get("difficulty") == level]
        if items:
            by_difficulty[level] = {
                "n": len(items),
                "exact": rate(items, "exact"),
                "lenient": rate(items, "lenient"),
            }
    latencies = sorted(r["seconds"] for r in records if r.get("seconds") is not None)
    return {
        "n": total,
        "execution_accuracy_exact": rate(records, "exact"),
        "execution_accuracy_lenient": rate(records, "lenient"),
        "validity_rate": (
            round(
                sum(1 for r in records if r["status"] not in ("rejected", "outage"))
                / total,
                3,
            )
            if total
            else 0.0
        ),
        "rejected": sum(1 for r in records if r["status"] == "rejected"),
        "query_failed": sum(1 for r in records if r["status"] == "query_failed"),
        "outage": sum(1 for r in records if r["status"] == "outage"),
        "retried": sum(1 for r in records if r.get("attempts", 1) > 1),
        "median_seconds": latencies[len(latencies) // 2] if latencies else None,
        "by_difficulty": by_difficulty,
    }
