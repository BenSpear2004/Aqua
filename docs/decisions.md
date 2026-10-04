# Decisions

Each entry records the decision, the alternatives considered, and why.

## October 2026: Stack and layout

**Decision.** FastAPI backend with the NL2SQL pipeline in `backend/nl2sql/`, React and Vite frontend, Gemini API (AI Studio keys) as the model, PostgreSQL on Tiger Cloud as the database, deployed with docker-compose at `/srv/bank-ai`.

**Alternatives.** Streamlit UI with code in `src/nl2sql/` (the original plan); Ollama as the primary model (the starter code).

**Reasoning.** The repo already had a working FastAPI, React, and docker-compose setup, and the frontend owner is building in React, so Streamlit would have been thrown away. Gemini's free API tier is stronger than models the server can run locally. Ollama stays available for serving the fine-tuned open model later, behind the same `llm.py` interface. The model name is read from env so the team can switch to whichever Gemini or Gemma model performs best without code changes.

## October 2026: Ollama qwen3:8b as the default model, Gemini as backup

**Decision.** Use `qwen3:8b` on Ben's Ollama server (reached over Tailscale) as the default model, with reasoning on. Keep Gemini as an optional backup behind the same `llm.py` interface. This changes the model part of the stack decision above.

**Alternatives.** Gemini (`gemini-3.6-flash`) as the only model; `qwen3:4b` (Ben's original default); `qwen2.5-coder:7b`; `qwen3:8b` with reasoning off.

**Reasoning.** Gemini's free tier turned out to allow only 20 requests per day per project for `gemini-3.6-flash`, and over several days most calls returned 503 (high demand); the SDK's automatic retries also used up quota without returning answers. That is not enough for the Phase 3 evaluation. On Ben's server there is no quota. Run against a SQLite copy of Sakila on 18 test questions, `qwen3:8b` with reasoning on got 18/18; with reasoning off it was about 13x faster but got one revenue query wrong while still running without error, so reasoning stays on by default. `qwen2.5-coder:7b` got 3 of 5 on an earlier set and `qwen3:4b` cannot turn reasoning off. Replies are constrained to `{"sql": ...}` with a JSON schema, which stopped reasoning text from leaking into the SQL.
