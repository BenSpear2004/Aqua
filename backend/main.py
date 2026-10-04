import logging
import os

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from nl2sql.config import load_settings
from nl2sql.db import DatabaseError
from nl2sql.llm import LLMError
from nl2sql.pipeline import answer_question, load_default_schema
from nl2sql.response import outage_response, to_response

app = FastAPI(title="Bank AI")

OLLAMA_URL = os.getenv(
    "OLLAMA_BASE_URL", "http://127.0.0.1:11434"
).rstrip("/")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3:4b")
DATABASE_URL = os.getenv("DATABASE_URL", "")


class ChatRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=10000)


async def ollama_request(method: str, path: str, payload=None):
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(180.0, connect=10.0)
        ) as client:
            response = await client.request(
                method, f"{OLLAMA_URL}{path}", json=payload
            )
            response.raise_for_status()
            return response.json()
    except httpx.TimeoutException:
        raise HTTPException(504, "Ollama took too long to respond.")
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            raise HTTPException(
                502, "Ollama model or endpoint not found. Check OLLAMA_MODEL."
            )
        raise HTTPException(502, "Ollama returned an error.")
    except httpx.RequestError:
        raise HTTPException(503, "Cannot connect to Ollama.")
    except ValueError:
        raise HTTPException(502, "Ollama returned invalid JSON.")


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "database_configured": bool(DATABASE_URL),
    }


@app.get("/api/models")
async def models():
    return await ollama_request("GET", "/api/tags")


@app.post("/api/chat")
async def chat(request: ChatRequest):
    data = await ollama_request(
        "POST",
        "/api/chat",
        {
            "model": OLLAMA_MODEL,
            "messages": [
                {"role": "user", "content": request.prompt}
            ],
            "stream": False,
        },
    )
    answer = data.get("message", {}).get("content")
    if not isinstance(answer, str):
        raise HTTPException(502, "Unexpected response from Ollama.")
    return {"answer": answer}


# ---- NL2SQL pipeline ----

log = logging.getLogger("aqua")

# Loaded once at startup. The schema file is temporary until schema.py.
SETTINGS = load_settings()
SCHEMA = load_default_schema()


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
        answer = answer_question(request.question, SETTINGS, SCHEMA)
    except LLMError as exc:
        log.warning("model unavailable: %s", exc)
        return JSONResponse(
            status_code=503,
            content=outage_response("model_unavailable", "The language model is not reachable right now."),
        )
    except DatabaseError as exc:
        log.warning("database unavailable: %s", exc)
        return JSONResponse(
            status_code=503,
            content=outage_response("database_unavailable", "The database is not reachable right now."),
        )
    return to_response(answer)
