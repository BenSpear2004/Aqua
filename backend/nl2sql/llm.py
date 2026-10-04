"""The one place in the pipeline that calls the language model.

Two providers sit behind the same complete() call: Ollama (the default,
qwen3:8b on Ben's server) and the Gemini API (the backup, or the demo
model when a paid key is set). settings.llm_provider picks one.
Everything about how each is called lives here: sampling settings,
reasoning, structured output, timeouts and error handling. Other modules
send text and get text back.
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

# The Gemini SDK wants milliseconds. Same headroom as Ollama.
GEMINI_TIMEOUT_MS = 180_000

# The SDK retries on its own by default, which burned the free daily
# quota in testing. Two attempts rides out one brief 429 or 503.
GEMINI_ATTEMPTS = 2


class LLMError(RuntimeError):
    """Raised for any failure to get a usable reply from the model."""


@dataclass(frozen=True)
class Completion:
    """The model's reply.

    `thinking` is the reasoning the model wrote before answering (empty
    when reasoning is off, and for Gemini, which does not return it). It
    is kept separate from `text` so it never gets mixed into the SQL.
    """

    text: str
    thinking: str
    model: str


def complete(
    prompt: str,
    settings: Settings,
    system: str | None = None,
    json_schema: dict[str, Any] | None = None,
    client: Any = None,
) -> Completion:
    """Send one prompt to the configured provider and return the reply.

    `json_schema`, if given, constrains the reply to JSON matching that
    schema, so callers get exactly the fields they asked for instead of
    free text.

    `client` exists for tests: an httpx.Client for Ollama, or a stand-in
    for the Gemini SDK client. Normal callers leave it out.
    """
    if settings.llm_provider == "gemini":
        return _complete_gemini(prompt, settings, system, json_schema, client)
    return _complete_ollama(prompt, settings, system, json_schema, client)


def _complete_ollama(
    prompt: str,
    settings: Settings,
    system: str | None,
    json_schema: dict[str, Any] | None,
    client: httpx.Client | None,
) -> Completion:
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


def _complete_gemini(
    prompt: str,
    settings: Settings,
    system: str | None,
    json_schema: dict[str, Any] | None,
    client: Any,
) -> Completion:
    """Gemini API through the google-genai SDK.

    Gemma models on the API take neither a system instruction nor a JSON
    schema, so for them the rules go at the top of the prompt and
    generate.extract_sql reads the SQL out of a code fence instead.
    Temperature is left at the API default, which Google recommends for
    current Gemini models.
    """
    if not settings.gemini_api_key:
        raise LLMError("GEMINI_API_KEY is not set, so Gemini cannot be used.")
    from google.genai import errors, types  # Ollama-only setups never load it

    model = settings.gemini_model
    # No tools are passed, so automatic function calling only adds a
    # warning to every call's log; switch it off.
    config: dict[str, Any] = {
        "seed": SEED,
        "automatic_function_calling": types.AutomaticFunctionCallingConfig(
            disable=True
        ),
    }
    contents = prompt
    if model.lower().startswith("gemma"):
        if system:
            contents = f"{system}\n\n{prompt}"
    else:
        if system:
            config["system_instruction"] = system
        if json_schema is not None:
            config["response_mime_type"] = "application/json"
            config["response_json_schema"] = json_schema

    if client is None:
        from google import genai

        client = genai.Client(
            api_key=settings.gemini_api_key,
            http_options=types.HttpOptions(
                timeout=GEMINI_TIMEOUT_MS,
                retry_options=types.HttpRetryOptions(attempts=GEMINI_ATTEMPTS),
            ),
        )
    try:
        response = client.models.generate_content(
            model=model,
            contents=contents,
            config=types.GenerateContentConfig(**config),
        )
    except errors.APIError as exc:
        raise LLMError(f"Gemini returned HTTP {exc.code}: {exc.message}") from exc
    except httpx.TimeoutException as exc:
        raise LLMError("Gemini took too long to respond.") from exc
    except httpx.HTTPError as exc:
        raise LLMError(f"Cannot reach the Gemini API: {exc}") from exc

    text = (response.text or "").strip()
    if not text:
        candidates = getattr(response, "candidates", None) or []
        reason = candidates[0].finish_reason if candidates else "blocked or empty"
        raise LLMError(f"Gemini returned no answer (stop reason: {reason}).")
    return Completion(
        text=text,
        thinking="",
        model=getattr(response, "model_version", None) or model,
    )
