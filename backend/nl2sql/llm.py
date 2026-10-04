"""The one place in the pipeline that calls the language model.

Two providers sit behind the same complete() call: the Gemini API (free
Gemini Flash-Lite in production) and Ollama (qwen3 on Ben's server).
settings.llm_provider picks one. When the Gemini model is down or out of
quota and settings.llm_fallback is on, the same prompt goes to each of
settings.gemini_fallback_models (Gemma 4 26B by default), then to
Ollama, so the user gets an answer rather than an outage. Everything about how each
provider is called lives here: sampling settings, reasoning, structured
output, timeouts, retries and error handling. Other modules send text
and get text back.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from typing import Any

import httpx

from nl2sql.config import Settings

log = logging.getLogger(__name__)

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

# Retries for Gemini's own server errors. The free tier returned HTTP 500
# or 503 on 28% of eval questions with two quick attempts, so allow three
# with a short backoff (about 2 s, then 4 s). 429 is left out on purpose:
# retrying a spent quota only spends more; the Ollama fallback covers it.
GEMINI_ATTEMPTS = 3
GEMINI_RETRY_DELAY_S = 2.0
GEMINI_RETRY_MAX_DELAY_S = 8.0
GEMINI_RETRY_CODES = [500, 502, 503, 504]

# Gemini failures worth answering with Ollama instead: Google's outages,
# a spent quota, and timeouts. Bad keys or model names (400, 403, 404)
# are configuration mistakes, so they fail loudly instead.
FALLBACK_CODES = frozenset({429, 500, 502, 503, 504})


class LLMError(RuntimeError):
    """Raised for any failure to get a usable reply from the model.

    `transient` is True when the provider was down, slow or out of quota,
    so another provider may succeed; False for configuration mistakes.
    """

    def __init__(self, message: str, transient: bool = False) -> None:
        super().__init__(message)
        self.transient = transient


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

    The returned Completion's `model` names the model that actually
    answered, so a fallback is visible to the caller.
    """
    chain = fallback_chain(settings)
    last_error: LLMError | None = None
    for index, (provider, model) in enumerate(chain):
        # A test client is a stand-in for the first provider (an httpx client
        # for Ollama, an SDK stand-in for Gemini), so it serves that provider.
        step_client = client if provider == chain[0][0] else None
        try:
            if provider == "ollama":
                # Ollama gets the system rules and JSON schema Gemma cannot.
                return _complete_ollama(
                    prompt, settings, system, json_schema, step_client
                )
            return _complete_gemini(
                prompt,
                replace(settings, gemini_model=model),
                system,
                json_schema,
                step_client,
            )
        except LLMError as exc:
            last_error = exc
            # A Gemini configuration mistake (bad key or model name) stops
            # the chain so it gets fixed. Ollama on Ben's machine is often
            # simply off, so any Ollama failure moves on.
            if provider == "gemini" and not exc.transient:
                raise
            if index + 1 < len(chain):
                log.warning(
                    "%s unavailable, trying the next model: %s", model or provider, exc
                )
    assert last_error is not None
    raise last_error


def fallback_chain(settings: Settings) -> list[tuple[str, str | None]]:
    """(provider, Gemini model) pairs, in the order to try them.

    Gemini (the default): the main Gemini model, then Ollama, then each of
    gemini_fallback_models. Ollama: Ollama first, then the Gemini models.
    With llm_fallback off, only the first step. Gemini steps after the
    first need an API key.
    """
    gemini = [settings.gemini_model] + [
        m for m in settings.gemini_fallback_models if m != settings.gemini_model
    ]
    if settings.llm_provider == "gemini":
        steps = [("gemini", gemini[0]), ("ollama", None)]
        steps += [("gemini", model) for model in gemini[1:]]
    else:
        steps = [("ollama", None)] + [("gemini", model) for model in gemini]
    if not settings.llm_fallback:
        return steps[:1]
    return [
        step
        for index, step in enumerate(steps)
        if index == 0 or step[0] == "ollama" or settings.gemini_api_key
    ]


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
                retry_options=types.HttpRetryOptions(
                    attempts=GEMINI_ATTEMPTS,
                    initial_delay=GEMINI_RETRY_DELAY_S,
                    max_delay=GEMINI_RETRY_MAX_DELAY_S,
                    http_status_codes=GEMINI_RETRY_CODES,
                ),
            ),
        )
    try:
        response = client.models.generate_content(
            model=model,
            contents=contents,
            config=types.GenerateContentConfig(**config),
        )
    except errors.APIError as exc:
        raise LLMError(
            f"Gemini returned HTTP {exc.code}: {exc.message}",
            transient=exc.code in FALLBACK_CODES,
        ) from exc
    except httpx.TimeoutException as exc:
        raise LLMError("Gemini took too long to respond.", transient=True) from exc
    except httpx.HTTPError as exc:
        raise LLMError(f"Cannot reach the Gemini API: {exc}", transient=True) from exc

    text = (response.text or "").strip()
    if not text:
        candidates = getattr(response, "candidates", None) or []
        reason = candidates[0].finish_reason if candidates else "blocked or empty"
        # An empty reply (a safety or recitation stop) may not repeat on
        # another model, so let the chain move on.
        raise LLMError(
            f"Gemini returned no answer (stop reason: {reason}).", transient=True
        )
    return Completion(
        text=text,
        thinking="",
        model=getattr(response, "model_version", None) or model,
    )
