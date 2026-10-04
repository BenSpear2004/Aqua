"""Answer a question end to end: build context, generate SQL, validate, run.

This is the one place the steps are put together, so the order and the
safety rule live here: SQL the validator rejects is never executed.

Problems with the question's SQL (rejected by the validator, or refused
by the database) come back inside the Answer as an error, so the user
can see the SQL and the reason. When the problem is one the model could
fix (a typo, a wrong column), it gets one more try with the error in
front of it. Problems with the service itself (model or database
unreachable) raise LLMError or DatabaseError for the API to report as a
server error.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Protocol

from nl2sql.config import Settings
from nl2sql.execute import DEFAULT_MAX_ROWS, QueryError, execute
from nl2sql.generate import Attempt, Example, generate_sql
from nl2sql.schema import Schema
from nl2sql.validate import UnsafeQueryError, validate_sql

log = logging.getLogger(__name__)

# One first try plus one correction. More rarely helps and doubles the
# wait each time with reasoning on.
MAX_ATTEMPTS = 2

# A query cancelled by statement_timeout is too slow, not wrong; asking
# again would just run another slow query.
_TIMEOUT_MARKER = "statement timeout"


@dataclass(frozen=True)
class Context:
    """What the model sees besides the question."""

    schema_text: str
    examples: tuple[Example, ...] = ()
    tables: tuple[str, ...] = ()


class Retriever(Protocol):
    """Anything that can pick the relevant context for a question."""

    def select(self, question: str, schema: Schema) -> Context: ...


@dataclass(frozen=True)
class Answer:
    """Everything the API needs to reply to one question.

    sql is the statement that ran (with its row limit), or the last one
    the model wrote if it was rejected. error_code is "rejected" when the
    validator refused the SQL and "query_failed" when the database did;
    both are None on success. attempts counts model calls (1 or 2).
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
    attempts: int = 1
    used_retrieval: bool = False


def full_context(schema: Schema) -> Context:
    """Every table, no examples: the baseline without retrieval."""
    return Context(schema_text=schema.to_prompt(), tables=tuple(sorted(schema.tables)))


def build_context(
    question: str, schema: Schema, retriever: Retriever | None
) -> tuple[Context, bool]:
    """Pick the context, falling back to the full schema if retrieval fails.

    Retrieval only narrows what the model sees, so when it is down (no
    embedding quota, network) the question is still answered, just
    without examples. Returns the context and whether retrieval was used.
    """
    if retriever is None:
        return full_context(schema), False
    try:
        return retriever.select(question, schema), True
    except (
        Exception
    ) as exc:  # noqa: BLE001 - any retrieval failure has the same fallback
        log.warning("retrieval failed, using the full schema: %s", exc)
        return full_context(schema), False


def answer_question(
    question: str,
    settings: Settings,
    schema: Schema,
    retriever: Retriever | None = None,
    max_rows: int = DEFAULT_MAX_ROWS,
) -> Answer:
    """Turn a question into rows, or into a clear reason it could not.

    Raises ValueError for an empty question, llm.LLMError if the model
    is unreachable and db.DatabaseError if the database is.
    """
    question = question.strip()
    if not question:
        raise ValueError("Question is empty.")

    context, used_retrieval = build_context(question, schema, retriever)
    previous: Attempt | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        generation = generate_sql(
            question,
            context.schema_text,
            settings,
            examples=context.examples,
            previous=previous,
        )
        base = {
            "question": question,
            "thinking": generation.thinking,
            "model": generation.model,
            "attempts": attempt,
            "used_retrieval": used_retrieval,
        }
        try:
            query = validate_sql(generation.sql, allowed_tables=schema.allowed_tables)
            result = execute(query, settings, max_rows=max_rows)
        except UnsafeQueryError as exc:
            error, code, fixable = str(exc), "rejected", exc.fixable
        except QueryError as exc:
            error, code = str(exc), "query_failed"
            fixable = _TIMEOUT_MARKER not in error
        else:
            return Answer(
                sql=result.sql,
                columns=result.columns,
                rows=result.rows,
                truncated=result.truncated,
                **base,
            )

        if not fixable or attempt == MAX_ATTEMPTS:
            return Answer(sql=generation.sql, error=error, error_code=code, **base)
        previous = Attempt(generation.sql, error)

    raise AssertionError("unreachable: the loop always returns")
