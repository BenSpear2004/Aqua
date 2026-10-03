import os

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

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
