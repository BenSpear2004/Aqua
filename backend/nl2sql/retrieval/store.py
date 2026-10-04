"""Fill the retrieval schema: one embedded description per table, and the
eval set's training questions as worked examples.

Run by a person, not the web app, after the schema or the dataset
changes. From backend/, with INDEXER_DATABASE_URL and GEMINI_API_KEY set:

    python -m nl2sql.retrieval.store            # update what changed
    python -m nl2sql.retrieval.store --dry-run  # show what would change

Reads the schema as the reader role and writes only as nl2sql_indexer,
which can touch the retrieval schema and nothing else. Only rows whose
text or embedding model changed are re-embedded, so a re-run costs no
API calls when nothing changed.

Only questions marked "train" are stored. Storing a "test" question
would let the model see the answer it is graded on.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import psycopg
from sqlglot import exp

from nl2sql.config import Settings, load_settings
from nl2sql.db import DatabaseError
from nl2sql.retrieval.embed import EmbeddingError, document_text, embed, to_pgvector
from nl2sql.schema import Schema, get_schema
from nl2sql.validate import UnsafeQueryError, validate_sql

DEFAULT_DATASET = (
    Path(__file__).resolve().parents[3] / "eval" / "datasets" / "pagila_v1.jsonl"
)


@dataclass(frozen=True)
class StoredExample:
    question: str
    sql: str
    tables: tuple[str, ...]


def content_hash(text: str, model: str) -> str:
    """Changes when the text or the embedding model changes."""
    return hashlib.sha256(f"{model}\n{text}".encode()).hexdigest()


def load_examples(path: Path, schema: Schema) -> list[StoredExample]:
    """The dataset's training questions, each checked by the validator.

    An example is shown to the model as a pattern, so one that the
    validator would reject must never be stored.
    """
    examples = []
    for number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not line.strip():
            continue
        item = json.loads(line)
        if item.get("split") != "train":
            continue
        try:
            tree = validate_sql(item["sql"], allowed_tables=schema.allowed_tables)
        except UnsafeQueryError as exc:
            raise ValueError(
                f"{path.name} line {number} ({item.get('id')}): {exc}"
            ) from exc
        tables = tuple(
            sorted(
                {t.name.lower() for t in tree.find_all(exp.Table)}
                & schema.allowed_tables
            )
        )
        examples.append(StoredExample(item["question"], item["sql"], tables))
    return examples


def sync_schema_docs(
    conn: psycopg.Connection, schema: Schema, settings: Settings, dry_run: bool
) -> dict[str, int]:
    """Embed new or changed table descriptions; drop tables that are gone."""
    model = settings.gemini_embed_model
    wanted = {name: schema.describe(name) for name in sorted(schema.tables)}
    existing = dict(
        conn.execute(
            "SELECT table_name, content_hash FROM retrieval.schema_doc"
        ).fetchall()
    )
    changed = [
        n for n, text in wanted.items() if existing.get(n) != content_hash(text, model)
    ]
    stale = sorted(set(existing) - set(wanted))
    if not dry_run and changed:
        vectors = embed([document_text(n, wanted[n]) for n in changed], settings)
        for name, vector in zip(changed, vectors):
            conn.execute(
                """
                INSERT INTO retrieval.schema_doc (table_name, content, content_hash, embedding, embed_model)
                VALUES (%s, %s, %s, %s::vector, %s)
                ON CONFLICT (table_name) DO UPDATE SET
                    content = EXCLUDED.content, content_hash = EXCLUDED.content_hash,
                    embedding = EXCLUDED.embedding, embed_model = EXCLUDED.embed_model,
                    updated_at = now()
                """,
                (
                    name,
                    wanted[name],
                    content_hash(wanted[name], model),
                    to_pgvector(vector),
                    model,
                ),
            )
    if not dry_run and stale:
        conn.execute(
            "DELETE FROM retrieval.schema_doc WHERE table_name = ANY(%s)", (stale,)
        )
    return {
        "tables embedded": len(changed),
        "tables removed": len(stale),
        "tables total": len(wanted),
    }


def sync_examples(
    conn: psycopg.Connection,
    examples: Sequence[StoredExample],
    settings: Settings,
    dry_run: bool,
) -> dict[str, int]:
    """Make the eval_train rows match the dataset's training questions."""
    model = settings.gemini_embed_model
    rows = conn.execute(
        "SELECT question, sql, embed_model FROM retrieval.example_query WHERE source = 'eval_train'"
    ).fetchall()
    existing = {question: (sql, row_model) for question, sql, row_model in rows}
    wanted = {e.question: e for e in examples}
    changed = [e for e in examples if existing.get(e.question) != (e.sql, model)]
    stale = sorted(set(existing) - set(wanted))
    if not dry_run and changed:
        vectors = embed(
            [document_text("question", e.question) for e in changed], settings
        )
        for example, vector in zip(changed, vectors):
            conn.execute(
                """
                INSERT INTO retrieval.example_query
                    (question, sql, tables, source, verified, embedding, embed_model)
                VALUES (%s, %s, %s, 'eval_train', true, %s::vector, %s)
                ON CONFLICT (question) DO UPDATE SET
                    sql = EXCLUDED.sql, tables = EXCLUDED.tables, source = EXCLUDED.source,
                    verified = true, embedding = EXCLUDED.embedding, embed_model = EXCLUDED.embed_model
                """,
                (
                    example.question,
                    example.sql,
                    list(example.tables),
                    to_pgvector(vector),
                    model,
                ),
            )
    if not dry_run and stale:
        conn.execute(
            "DELETE FROM retrieval.example_query WHERE source = 'eval_train' AND question = ANY(%s)",
            (stale,),
        )
    return {
        "examples embedded": len(changed),
        "examples removed": len(stale),
        "examples total": len(wanted),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Embed the schema and training examples into the retrieval schema."
    )
    parser.add_argument(
        "--dataset", type=Path, default=DEFAULT_DATASET, help="JSONL eval dataset"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="report what would change, embed nothing"
    )
    args = parser.parse_args(argv)

    settings = load_settings()
    if not settings.indexer_database_url:
        print("INDEXER_DATABASE_URL is not set. See .env.example.")
        return 1
    try:
        schema = get_schema(settings)
        examples = load_examples(args.dataset, schema)
        with psycopg.connect(settings.indexer_database_url, connect_timeout=10) as conn:
            report = sync_schema_docs(conn, schema, settings, args.dry_run)
            report |= sync_examples(conn, examples, settings, args.dry_run)
    except (DatabaseError, EmbeddingError, ValueError, psycopg.Error) as exc:
        print(f"Indexing failed, nothing was saved: {exc}")
        return 1
    prefix = "Would change" if args.dry_run else "Done"
    print(
        f"{prefix} ({settings.gemini_embed_model}): "
        + ", ".join(f"{k} {v}" for k, v in report.items())
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
