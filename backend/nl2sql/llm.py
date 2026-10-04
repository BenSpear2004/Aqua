"""The one place in the pipeline that calls the language model (Ollama).

Everything about how the model is called lives here: the sampling
settings, reasoning on or off, structured output, timeouts and error
handling. Other modules send text and get text back.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from nl2sql.config import Settings

# Qwen's recommended sampling for each mode. Their model card advises
# against temperature 0 when reasoning is on.
THINKING_OPTIONS = {"temperature": 0.6, "top_p": 0.95, "top_k": 20}
NON_THINKING_OPTIONS = {"temperature": 0.7, "top_p": 0.8, "top_k": 20}

# A fixed seed makes the same question give the same answer, which keeps
# test runs comparable without forcing temperature to 0.
SEED = 42

# Context window in tokens. Ollama's default can be small; the schema plus
# a long reasoning trace needs more room than that, or the reply is cut off.
NUM_CTX = 16384

# Reasoning answers took up to ~40s in testing; allow plenty of headroom.
TIMEOUT = httpx.Timeout(180.0, connect=10.0)


class LLMError(RuntimeError):
    """Raised for any failure to get a usable reply from the model."""


@dataclass(frozen=True)
class Completion:
    """The model's reply.

    `thinking` is the reasoning the model wrote before answering (empty
    when reasoning is off). It is kept separate from `text` so it never
    gets mixed into the SQL, and so it can be logged or shown to users.
    """

    text: str
    thinking: str
    model: str


def complete(
    prompt: str,
    settings: Settings,
    system: str | None = None,
    json_schema: dict[str, Any] | None = None,
    client: httpx.Client | None = None,
) -> Completion:
    """Send one prompt to Ollama and return the reply.

    `json_schema`, if given, makes Ollama constrain the reply to JSON
    matching that schema, so callers get exactly the fields they asked
    for instead of free text.

    `client` exists for tests, which pass one that never touches the
    network. Normal callers leave it out.
    """
    messages = [{"role": "user", "content": prompt}]
    if system:
        messages.insert(0, {"role": "system", "content": system})

    options = THINKING_OPTIONS if settings.ollama_think else NON_THINKING_OPTIONS
    body: dict[str, Any] = {
        "model": settings.ollama_model,
        "messages": messages,
        "stream": False,
        "think": settings.ollama_think,
        "options": {**options, "seed": SEED, "num_ctx": NUM_CTX},
    }
    if json_schema is not None:
        body["format"] = json_schema

    url = f"{settings.ollama_base_url}/api/chat"
    owns_client = client is None
    if owns_client:
        client = httpx.Client(timeout=TIMEOUT)
    try:
        response = client.post(url, json=body)
        response.raise_for_status()
        data = response.json()
    except httpx.TimeoutException as exc:
        raise LLMError(f"Ollama took too long to respond ({url}).") from exc
    except httpx.HTTPStatusError as exc:
        # Ollama explains errors in the body, e.g. a model that isn't pulled.
        detail = exc.response.text.strip()[:200]
        raise LLMError(
            f"Ollama returned HTTP {exc.response.status_code}: {detail}"
        ) from exc
    except httpx.RequestError as exc:
        raise LLMError(f"Cannot connect to Ollama at {url}: {exc}") from exc
    except ValueError as exc:
        raise LLMError("Ollama returned a reply that is not JSON.") from exc
    finally:
        if owns_client:
            client.close()

    message = data.get("message") or {}
    text = (message.get("content") or "").strip()
    if not text:
        reason = data.get("done_reason", "unknown")
        raise LLMError(f"Ollama returned no answer (stop reason: {reason}).")
    return Completion(
        text=text,
        thinking=(message.get("thinking") or "").strip(),
        model=data.get("model", settings.ollama_model),
    )
