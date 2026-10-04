"""Answer a question end to end: generate SQL, validate it, run it.

This is the one place the steps are put together, so the order and the
safety rule live here: SQL the validator rejects is never executed.

Problems with the question's SQL (rejected by the validator, or refused
by the database) come back inside the Answer as an error, so the user
can see the SQL and the reason. Problems with the service itself (model
or database unreachable) raise LLMError or DatabaseError for the API to
report as a server error.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from nl2sql.config import Settings
from nl2sql.execute import DEFAULT_MAX_ROWS, QueryError, execute
from nl2sql.generate import generate_sql, load_schema
from nl2sql.validate import UnsafeQueryError, validate_sql

# Temporary until Drew's schema.py reads the schema from the database.
SCHEMA_PATH = Path(__file__).parent / "pagila_schema.sql"


@dataclass(frozen=True)
class Answer:
    """Everything the API needs to reply to one question.

    sql is the statement that ran (with its row limit), or the one the
    model wrote if it was rejected. error_code is "rejected" when the
    validator refused the SQL and "query_failed" when the database did;
    both are None on success.
    """

    question: str
    sql: str
    columns: list[str] = field(default_factory=list)
    rows: list[tuple[Any, ...]] = field(default_factory=list)
    truncated: bool = False
    thinking: str = ""
    model: str = ""
    error: str | None = None
    error_code: str | None = None


def load_default_schema() -> str:
    """The schema text for the prompt, without its comment lines."""
    return load_schema(SCHEMA_PATH)


def answer_question(
    question: str,
    settings: Settings,
    schema: str,
    max_rows: int = DEFAULT_MAX_ROWS,
) -> Answer:
    """Turn a question into rows, or into a clear reason it could not.

    Raises ValueError for an empty question, llm.LLMError if the model
    is unreachable and db.DatabaseError if the database is.
    """
    generation = generate_sql(question, schema, settings)
    base = {"question": question, "thinking": generation.thinking, "model": generation.model}

    try:
        query = validate_sql(generation.sql)
        result = execute(query, settings, max_rows=max_rows)
    except UnsafeQueryError as exc:
        return Answer(sql=generation.sql, error=str(exc), error_code="rejected", **base)
    except QueryError as exc:
        return Answer(sql=generation.sql, error=str(exc), error_code="query_failed", **base)

    return Answer(
        sql=result.sql,
        columns=result.columns,
        rows=result.rows,
        truncated=result.truncated,
        **base,
    )
