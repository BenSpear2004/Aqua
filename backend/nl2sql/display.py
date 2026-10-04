"""Make result tables readable, using the database's own comments.

The bank database stores codes (PRIJEM, loan status B) and unnamed
columns (a11). Its comments, written in db/financial/02_load.sql, say
what they mean. This module turns them into display rules:

- value labels: PRIJEM -> "Credit (money in)"
- column labels: a11 -> "Average salary"
- the currency, from a table comment such as "Amounts in Czech crowns (CZK)."

The comments are the only source, so nothing here names a bank table,
and a database without comments (Pagila) displays exactly as before.
The SQL the user sees still has the real codes.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from nl2sql.schema import Schema

# "CODE = meaning" pairs are separated by ", " or "; " (or follow a
# "Purpose: " lead-in) where the next piece is itself "... = ...".
# Meanings may contain commas: "A = finished, paid off; B = ...".
_PAIR_SPLIT = re.compile(r"[,;:] (?=[^,;:=]+ = )")
# Codes are upper case: PRIJEM, POPLATEK MESICNE, SANKC. UROK, B.
_CODE = re.compile(r"^[A-Z][A-Z.]*(?: [A-Z][A-Z.]*)*$")
# An ISO currency code in brackets, e.g. "(CZK)".
_CURRENCY = re.compile(r"\(([A-Z]{3})\)")

# A comment longer than this reads as a sentence, not a column header.
MAX_LABEL_LENGTH = 50


@dataclass(frozen=True)
class Display:
    """How to show one database's results. Empty means show them as is."""

    # Column name -> code -> meaning.
    values_by_column: dict[str, dict[str, str]] = field(default_factory=dict)
    # Codes with one meaning wherever they appear, for columns the query
    # renamed (SELECT type AS kind). One-letter codes such as loan
    # status B are too ambiguous to apply outside their own column.
    values_anywhere: dict[str, str] = field(default_factory=dict)
    # Column name -> header, e.g. a11 -> "Average salary".
    column_labels: dict[str, str] = field(default_factory=dict)
    # ISO code for money columns; None keeps the frontend's default.
    currency: str | None = None

    def value(self, column: str, value: Any) -> Any:
        """One cell as the user should see it."""
        if not isinstance(value, str):
            return value
        labels = self.values_by_column.get(column.lower(), {})
        if value in labels:
            return labels[value]
        return self.values_anywhere.get(value, value)

    def rows(
        self, columns: Sequence[str], rows: Sequence[Sequence[Any]]
    ) -> list[tuple[Any, ...]]:
        return [tuple(self.value(c, v) for c, v in zip(columns, row)) for row in rows]


def _sentence(text: str) -> str:
    text = text.strip().rstrip(".;").strip()
    return text[:1].upper() + text[1:]


def code_meanings(comment: str) -> dict[str, str]:
    """The CODE = meaning pairs in one comment; lower-case keys such as
    "empty = not given" are descriptions, not codes, and are skipped."""
    meanings = {}
    for piece in _PAIR_SPLIT.split(comment):
        code, sep, meaning = piece.partition(" = ")
        if sep and _CODE.match(code.strip()):
            meanings[code.strip()] = _sentence(meaning)
    return meanings


def header(comment: str) -> str | None:
    """A short column header from a comment, or None if it is not one.

    "Average salary." -> "Average salary"; "Purpose: POJISTNE = ..." ->
    "Purpose"; a bare list of codes has no header.
    """
    if ":" in comment:
        comment = comment.split(":", 1)[0]
    elif " = " in comment:
        return None
    text = _sentence(comment)
    return text if text and len(text) <= MAX_LABEL_LENGTH else None


def display_for(schema: Schema) -> Display:
    """The display rules implied by the schema's comments."""
    by_column: dict[str, dict[str, str]] = {}
    meanings_of: dict[str, set[str]] = {}
    headers: dict[str, set[str | None]] = {}
    currencies: set[str] = set()

    for table in schema.tables.values():
        currencies.update(_CURRENCY.findall(table.comment))
        for column in table.columns:
            name = column.name.lower()
            meanings = code_meanings(column.comment)
            if meanings:
                by_column.setdefault(name, {}).update(meanings)
                for code, meaning in meanings.items():
                    meanings_of.setdefault(code, set()).add(meaning)
            headers.setdefault(name, set()).add(header(column.comment) if column.comment else None)

    return Display(
        values_by_column=by_column,
        values_anywhere={
            code: next(iter(found))
            for code, found in meanings_of.items()
            if len(found) == 1 and len(code) > 1
        },
        # Only when every column of that name agrees, so a date column
        # is not labelled with the one table's comment that has one.
        column_labels={
            name: next(iter(found))
            for name, found in headers.items()
            if len(found) == 1 and None not in found
        },
        currency=next(iter(currencies)) if len(currencies) == 1 else None,
    )
