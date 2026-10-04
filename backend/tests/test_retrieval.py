"""Tests for nl2sql/retrieval: embedding, context assembly, the indexer's
dataset loading. No embedding API and no database: the API client is a
stand-in, and the database lookups are kept apart in VectorRetriever."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from nl2sql.config import Settings
from nl2sql.retrieval.embed import (
    EMBED_DIMENSIONS,
    EmbeddingError,
    document_text,
    embed,
    embed_query,
    query_text,
    to_pgvector,
)
from nl2sql.retrieval.select import RetrievalError, assemble, choose_tables
from nl2sql.retrieval.store import content_hash, load_examples
from nl2sql.schema import Column, Schema, Table

SETTINGS = Settings(gemini_api_key="test-key", gemini_embed_model="gemini-embedding-2")


class FakeEmbedClient:
    """Answers embed_content like the SDK; records each request."""

    def __init__(self, dimensions: int = EMBED_DIMENSIONS, drop: int = 0) -> None:
        self.dimensions = dimensions
        self.drop = drop
        self.requests: list[dict] = []
        self.models = self

    def embed_content(self, model, contents, config):
        self.requests.append({"model": model, "contents": contents, "config": config})
        texts = [c.parts[0].text for c in contents][self.drop :]
        return SimpleNamespace(
            embeddings=[
                SimpleNamespace(values=[float(len(t))] * self.dimensions) for t in texts
            ]
        )


# ---- embed ----


def test_one_vector_per_text_each_in_its_own_content() -> None:
    client = FakeEmbedClient()
    vectors = embed(["a", "bb", "ccc"], SETTINGS, client)
    assert [v[0] for v in vectors] == [1.0, 2.0, 3.0]
    (request,) = client.requests
    assert len(request["contents"]) == 3  # three Contents, not one combined
    assert request["model"] == "gemini-embedding-2"
    assert request["config"].output_dimensionality == 768


def test_large_inputs_are_sent_in_batches() -> None:
    client = FakeEmbedClient()
    vectors = embed([f"t{i}" for i in range(45)], SETTINGS, client)
    assert len(vectors) == 45
    assert [len(r["contents"]) for r in client.requests] == [20, 20, 5]


def test_wrong_size_vectors_are_refused() -> None:
    with pytest.raises(EmbeddingError, match="768 dimensions"):
        embed(["a"], SETTINGS, FakeEmbedClient(dimensions=3072))


def test_missing_vectors_are_refused() -> None:
    """The API merging inputs into one vector must not go unnoticed."""
    with pytest.raises(EmbeddingError, match="Asked for 2"):
        embed(["a", "b"], SETTINGS, FakeEmbedClient(drop=1))


def test_no_api_key_is_a_clear_error() -> None:
    with pytest.raises(EmbeddingError, match="GEMINI_API_KEY"):
        embed(["a"], Settings())


def test_query_and_document_prefixes() -> None:
    client = FakeEmbedClient()
    embed_query("top films", SETTINGS, client)
    assert (
        client.requests[0]["contents"][0].parts[0].text
        == "task: search result | query: top films"
    )
    assert query_text("x") == "task: search result | query: x"
    assert document_text("film", "Table film") == "title: film | text: Table film"


def test_pgvector_text_form() -> None:
    assert to_pgvector([0.5, 1, -2.25]) == "[0.5,1.0,-2.25]"


# ---- choosing tables ----


def table(name: str, *columns: str, refs: tuple[str, ...] = ()) -> Table:
    return Table(
        name, tuple(Column(c, "integer", True) for c in columns), (), frozenset(refs)
    )


SCHEMA = Schema(
    tables={
        "film": table("film", "film_id", "title"),
        "category": table("category", "category_id", "name"),
        "film_category": table(
            "film_category", "film_id", "category_id", refs=("film", "category")
        ),
        "actor": table("actor", "actor_id"),
        "payment": table("payment", "payment_id", "customer_id"),
        "customer": table("customer", "customer_id"),
    }
)


def test_bridge_tables_are_added_between_chosen_tables() -> None:
    assert choose_tables(SCHEMA, ["film", "category"], []) == {
        "film",
        "category",
        "film_category",
    }


def test_example_tables_are_included_and_unknown_names_dropped() -> None:
    assert choose_tables(SCHEMA, ["payment"], ["customer", "retrieval_table"]) == {
        "payment",
        "customer",
    }


def test_assemble_builds_a_narrow_prompt_with_examples() -> None:
    context = assemble(
        SCHEMA,
        ["film", "category"],
        [("How many films?", "SELECT count(*) FROM film", ["film"])],
    )
    assert context.tables == ("category", "film", "film_category")
    assert "CREATE TABLE actor" not in context.schema_text
    assert context.examples[0].sql == "SELECT count(*) FROM film"


def test_empty_index_raises_so_the_pipeline_falls_back() -> None:
    with pytest.raises(RetrievalError, match="index is empty"):
        assemble(SCHEMA, [], [])


# ---- the indexer's dataset loading ----


def write_dataset(tmp_path: Path, *items: dict) -> Path:
    path = tmp_path / "set.jsonl"
    path.write_text("\n".join(json.dumps(i) for i in items) + "\n", encoding="utf-8")
    return path


def test_only_training_questions_are_loaded(tmp_path: Path) -> None:
    path = write_dataset(
        tmp_path,
        {
            "id": "t1",
            "split": "train",
            "question": "How many films?",
            "sql": "SELECT count(*) FROM film",
        },
        {
            "id": "x1",
            "split": "test",
            "question": "Graded question",
            "sql": "SELECT title FROM film",
        },
    )
    examples = load_examples(path, SCHEMA)
    assert [e.question for e in examples] == ["How many films?"]
    assert examples[0].tables == ("film",)


def test_unsafe_training_sql_stops_the_indexer(tmp_path: Path) -> None:
    path = write_dataset(
        tmp_path,
        {"id": "bad", "split": "train", "question": "q", "sql": "DELETE FROM film"},
    )
    with pytest.raises(ValueError, match="bad"):
        load_examples(path, SCHEMA)


def test_content_hash_changes_with_text_or_model() -> None:
    assert content_hash("a", "m1") != content_hash("b", "m1")
    assert content_hash("a", "m1") != content_hash("a", "m2")
    assert content_hash("a", "m1") == content_hash("a", "m1")
