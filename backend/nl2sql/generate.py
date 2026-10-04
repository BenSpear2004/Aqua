"""Turn a plain-English question into SQL using the model.

This module only generates. It does not validate or run anything; the
caller passes the result to validate.py first, so nothing here has to be
trusted.

The schema is a parameter rather than something this module loads
itself. Without retrieval the caller passes every table; with it, only
the relevant tables plus similar worked examples. On a retry the caller
also passes the SQL that failed and why, so the model can correct it.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass

import httpx

from nl2sql.config import Settings
from nl2sql.llm import complete

# The SQL dialect the model writes. Our Tiger Cloud database runs Postgres.
DIALECT_NAME = "PostgreSQL"

SYSTEM_INSTRUCTION = f"""\
You translate questions into SQL for a {DIALECT_NAME} database.

Rules:
- Answer with exactly one SQL SELECT statement.
- Use only the tables and columns in the schema you are given.
- Use {DIALECT_NAME} syntax.
- Text comparisons are case-sensitive. When comparing a column to any
  word or name taken from the question, use ILIKE instead of =.
- Name the columns you select; never use SELECT *.
- Give computed columns a short snake_case alias, such as total_revenue.
"""

# Ollama constrains the reply to JSON matching this, so the answer is
# exactly {"sql": "..."} with no explanation or markdown around it.
SQL_REPLY_SCHEMA = {
    "type": "object",
    "properties": {"sql": {"type": "string"}},
    "required": ["sql"],
}

# Fallback for replies that are not JSON: a markdown code fence, with or
# without a language tag.
_FENCE = re.compile(r"```(?:sql)?\s*(.*?)```", re.IGNORECASE | re.DOTALL)


@dataclass(frozen=True)
class Generation:
    """The generated SQL plus where it came from.

    `thinking` and `model` are kept for logging and for showing users
    why the model wrote what it did.
    """

    sql: str
    thinking: str
    model: str


@dataclass(frozen=True)
class Example:
    """A worked question and the SQL that answers it, shown to the model."""

    question: str
    sql: str


@dataclass(frozen=True)
class Attempt:
    """SQL that failed on an earlier try, and the reason it failed."""

    sql: str
    error: str


def build_prompt(
    question: str,
    schema: str,
    examples: Sequence[Example] = (),
    previous: Attempt | None = None,
) -> str:
    """Combine the schema, examples and question into the text the model sees.

    Schema first, question last, so the model reads the question with the
    tables already in view. Examples sit between them as patterns to
    follow. A failed attempt goes after the question, so the correction
    is the last thing the model reads.
    """
    parts = [f"Schema:\n{schema}"]
    if examples:
        shown = "\n\n".join(f"Question: {e.question}\nSQL: {e.sql}" for e in examples)
        parts.append(f"Examples of questions about this database and their SQL:\n{shown}")
    parts.append(f"Question: {question}")
    if previous is not None:
        parts.append(
            f"Your previous SQL was:\n{previous.sql}\n"
            f"It failed: {previous.error}\n"
            "Write a corrected query that answers the question."
        )
    return "\n\n".join(parts)


def extract_sql(reply: str) -> str:
    """Pull the SQL out of the model's reply.

    Normally the reply is {"sql": "..."} because of SQL_REPLY_SCHEMA. If
    it somehow is not, fall back to a code fence, then to the raw text,
    and let the validator decide whether what is left is usable.
    """
    try:
        parsed = json.loads(reply)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, dict) and isinstance(parsed.get("sql"), str):
        return parsed["sql"].strip()

    match = _FENCE.search(reply)
    return (match.group(1) if match else reply).strip()


def generate_sql(
    question: str,
    schema: str,
    settings: Settings,
    client: httpx.Client | None = None,
    examples: Sequence[Example] = (),
    previous: Attempt | None = None,
) -> Generation:
    """Ask the model for SQL answering `question`. The SQL is not validated.

    `examples` and `previous` are passed to build_prompt; see there.

    `client` is passed through to llm.complete so tests can avoid the
    network.

    Raises ValueError for an empty question and llm.LLMError if the
    model call fails.
    """
    question = question.strip()
    if not question:
        raise ValueError("Question is empty.")

    completion = complete(
        build_prompt(question, schema, examples, previous),
        settings,
        system=SYSTEM_INSTRUCTION,
        json_schema=SQL_REPLY_SCHEMA,
        client=client,
    )
    return Generation(
        sql=extract_sql(completion.text),
        thinking=completion.thinking,
        model=completion.model,
    )
