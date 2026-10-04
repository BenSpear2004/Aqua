"""HTTP routes. All the work happens in nl2sql.pipeline; this file only
turns requests into pipeline calls and pipeline results into JSON."""

import logging
from collections.abc import Awaitable, Callable
from dataclasses import replace
from typing import Any, Literal

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field

from auth.router import router as auth_router
from auth.security import UserSession, require_database_access
from nl2sql.config import load_settings
from nl2sql.db import DatabaseError
from nl2sql.display import display_for
from nl2sql.llm import LLMError
from nl2sql.pipeline import Retriever, answer_question
from nl2sql.response import outage_response, to_response
from nl2sql.schema import get_schema

app = FastAPI(title="Aqua")
log = logging.getLogger("aqua")

SETTINGS = load_settings()
app.state.settings = SETTINGS
app.include_router(auth_router)


@app.middleware("http")
async def private_api_responses(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """Keep identity and customer query results out of shared HTTP caches."""
    response = await call_next(request)
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
        vary = response.headers.get("Vary", "")
        if "cookie" not in {part.strip().lower() for part in vary.split(",")}:
            response.headers["Vary"] = f"{vary}, Cookie" if vary else "Cookie"
    return response


def _retriever() -> Retriever | None:
    """The vector retriever when RETRIEVAL is on, otherwise None.

    Imported only when on, so the app starts without the embedding SDK
    configured. If retrieval fails at question time, the pipeline falls
    back to the full schema.
    """
    if not SETTINGS.retrieval:
        return None
    from nl2sql.retrieval.select import VectorRetriever

    return VectorRetriever(SETTINGS)


RETRIEVER = _retriever()


def _model_name(provider: str) -> str:
    return SETTINGS.gemini_model if provider == "gemini" else SETTINGS.ollama_model


def available_models() -> list[dict[str, str]]:
    """The models this server can run, default first.

    Same shape as the frontend's model list, so its dropdown can be
    filled from here. Gemini is listed only when a key is set, so the
    UI never offers a choice that would fail.
    """
    models = {
        "ollama": {
            "id": "ollama",
            "name": SETTINGS.ollama_model,
            "description": "Open model on the team server",
        }
    }
    if SETTINGS.gemini_api_key:
        models["gemini"] = {
            "id": "gemini",
            "name": SETTINGS.gemini_model,
            "description": "Google Gemini API",
        }
    default = models.pop(SETTINGS.llm_provider, None)
    return ([default] if default else []) + list(models.values())


@app.get("/api/health")
def health():
    """Liveness for the Docker healthcheck. Never touches the database or
    model, so a slow dependency cannot mark the container unhealthy."""
    return {
        "status": "ok",
        "database_configured": bool(SETTINGS.database_url),
        "model": _model_name(SETTINGS.llm_provider),
        "retrieval": SETTINGS.retrieval,
    }


@app.get("/api/models")
def models():
    """The model choices for the frontend's dropdown."""
    return {"models": available_models()}


class QueryRequest(BaseModel):
    # Whitespace is trimmed first, so a blank question fails min_length
    # and FastAPI answers 422 before the model is called.
    model_config = ConfigDict(str_strip_whitespace=True)

    question: str = Field(min_length=1, max_length=2000)
    # An id from /api/models. Left out, the server default (LLM_PROVIDER)
    # is used; anything else is a 422.
    model: Literal["ollama", "gemini"] | None = None


@app.post("/api/query", response_model=None)
def query(
    request: QueryRequest,
    session: UserSession = Depends(require_database_access),
) -> dict[str, Any] | JSONResponse:
    """Answer a question with SQL, rows and the SQL that produced them.

    A plain def (not async): FastAPI runs it in a worker thread, so a
    slow model call does not hold up other requests. Rejected or failed
    queries return 200 with status "error" so the UI can show the SQL and
    the reason; an unreachable model or database returns 503. Details of
    outages are logged, not sent, so internal addresses stay private.
    """
    provider = request.model or SETTINGS.llm_provider
    if provider == "gemini" and not SETTINGS.gemini_api_key:
        body = outage_response(
            "model_not_configured", "Gemini is not set up on this server."
        )
        body["error"]["retryable"] = False  # asking again will not help
        return JSONResponse(status_code=400, content=body)
    settings = replace(SETTINGS, llm_provider=provider)

    try:
        schema = get_schema(settings)
        answer = answer_question(
            request.question, settings, schema, retriever=RETRIEVER
        )
    except LLMError as exc:
        log.warning("model unavailable (%s): %s", provider, exc)
        return JSONResponse(
            status_code=503,
            content=outage_response(
                "model_unavailable", "The language model is not reachable right now."
            ),
        )
    except DatabaseError as exc:
        log.warning("database unavailable: %s", exc)
        return JSONResponse(
            status_code=503,
            content=outage_response(
                "database_unavailable", "The database is not reachable right now."
            ),
        )
    return to_response(answer, display_for(schema))
