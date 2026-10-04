"""Turn text into vectors with the Gemini embedding model.

The only module that calls the embedding API, so the model name, the
vector size and the API's quirks live in one place:

- Several texts in one request come back as ONE combined vector unless
  each is wrapped in its own Content, so every text gets its own.
- gemini-embedding-2 takes no task type; the documented way to mark
  queries and documents is a text prefix, applied here.
- 768 dimensions must match vector(768) in db/04_retrieval.sql. The API
  normalizes shortened vectors, so cosine distance works as is.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import httpx

from nl2sql.config import Settings

EMBED_DIMENSIONS = 768

# Texts per request. Kept small so one failure loses little work.
BATCH_SIZE = 20


class EmbeddingError(RuntimeError):
    """Raised when the embedding API cannot produce usable vectors."""


def query_text(question: str) -> str:
    """How a user question is embedded, so it lands near similar documents."""
    return f"task: search result | query: {question}"


def document_text(title: str, text: str) -> str:
    """How a stored table description or example question is embedded."""
    return f"title: {title} | text: {text}"


def _client(settings: Settings) -> Any:
    if not settings.gemini_api_key:
        raise EmbeddingError("GEMINI_API_KEY is not set, so nothing can be embedded.")
    from google import genai  # imported here so the app starts without it

    return genai.Client(api_key=settings.gemini_api_key)


def embed(
    texts: Sequence[str], settings: Settings, client: Any = None
) -> list[list[float]]:
    """One 768-number vector per text, in the same order.

    `client` exists for tests, which pass a stand-in that never reaches
    the network. Raises EmbeddingError for any API or network failure.
    """
    from google.genai import errors, types

    client = client or _client(settings)
    config = types.EmbedContentConfig(output_dimensionality=EMBED_DIMENSIONS)
    vectors: list[list[float]] = []
    for start in range(0, len(texts), BATCH_SIZE):
        batch = texts[start : start + BATCH_SIZE]
        contents = [types.Content(parts=[types.Part(text=text)]) for text in batch]
        try:
            result = client.models.embed_content(
                model=settings.gemini_embed_model, contents=contents, config=config
            )
        except (errors.APIError, httpx.HTTPError) as exc:
            raise EmbeddingError(f"Embedding request failed: {exc}") from exc
        embeddings = result.embeddings or []
        if len(embeddings) != len(batch):
            raise EmbeddingError(
                f"Asked for {len(batch)} embeddings, got {len(embeddings)}."
            )
        for item in embeddings:
            values = list(item.values or [])
            if len(values) != EMBED_DIMENSIONS:
                raise EmbeddingError(
                    f"Expected {EMBED_DIMENSIONS} dimensions, got {len(values)}."
                )
            vectors.append(values)
    return vectors


def embed_query(question: str, settings: Settings, client: Any = None) -> list[float]:
    """The vector for one user question."""
    return embed([query_text(question)], settings, client)[0]


def to_pgvector(values: Sequence[float]) -> str:
    """The text form pgvector reads, e.g. '[0.1,0.2]', for a ::vector cast."""
    return "[" + ",".join(repr(float(v)) for v in values) + "]"
