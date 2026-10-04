"""Turn a plain-English question into SQL using the model.

This module only generates. It does not validate or run anything; the
caller passes the result to validate.py first, so nothing here has to be
trusted.

The schema is a parameter rather than something this module loads
itself. Today the caller passes the whole Sakila schema; later, retrieval
can pass only the relevant tables, rules and examples without this
module changing.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

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


def load_schema(path: Path) -> str:
    """Return a schema file's contents with comment lines removed.

    Header comments and license text are for people; sent to the model
    they only take up prompt space.
    """
    lines = path.read_text(encoding="utf-8").splitlines()
    kept = [line for line in lines if not line.lstrip().startswith("--")]
    return "\n".join(kept).strip()


def build_prompt(question: str, schema: str) -> str:
    """Combine the schema and the question into the text the model sees.

    Schema first, question last, so the model reads the question with the
    tables already in view.
    """
    return f"Schema:\n{schema}\n\nQuestion: {question}"


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
) -> Generation:
    """Ask the model for SQL answering `question`. The SQL is not validated.

    `client` is passed through to llm.complete so tests can avoid the
    network.

    Raises ValueError for an empty question and llm.LLMError if the
    model call fails.
    """
    question = question.strip()
    if not question:
        raise ValueError("Question is empty.")

    completion = complete(
        build_prompt(question, schema),
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
