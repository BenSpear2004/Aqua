"""HTTP routes. All the work happens in nl2sql.pipeline; this file only
turns requests into pipeline calls and pipeline results into JSON."""

import logging

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from nl2sql.config import load_settings
from nl2sql.db import DatabaseError
from nl2sql.llm import LLMError
from nl2sql.pipeline import Retriever, answer_question
from nl2sql.response import outage_response, to_response
from nl2sql.schema import get_schema

app = FastAPI(title="Aqua")
log = logging.getLogger("aqua")

SETTINGS = load_settings()


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


@app.get("/api/health")
def health():
    """Liveness for the Docker healthcheck. Never touches the database or
    model, so a slow dependency cannot mark the container unhealthy."""
    return {
        "status": "ok",
        "database_configured": bool(SETTINGS.database_url),
        "model": SETTINGS.ollama_model,
        "retrieval": SETTINGS.retrieval,
    }


class QueryRequest(BaseModel):
    # Whitespace is trimmed first, so a blank question fails min_length
    # and FastAPI answers 422 before the model is called.
    model_config = ConfigDict(str_strip_whitespace=True)

    question: str = Field(min_length=1, max_length=2000)


@app.post("/api/query")
def query(request: QueryRequest):
    """Answer a question with SQL, rows and the SQL that produced them.

    A plain def (not async): FastAPI runs it in a worker thread, so a
    slow model call does not hold up other requests. Rejected or failed
    queries return 200 with status "error" so the UI can show the SQL and
    the reason; an unreachable model or database returns 503. Details of
    outages are logged, not sent, so internal addresses stay private.
    """
    try:
        schema = get_schema(SETTINGS)
        answer = answer_question(
            request.question, SETTINGS, schema, retriever=RETRIEVER
        )
    except LLMError as exc:
        log.warning("model unavailable: %s", exc)
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
    return to_response(answer)
