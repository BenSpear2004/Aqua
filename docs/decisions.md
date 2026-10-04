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

## October 2026: Audie's Tiger Cloud service is the production database

**Decision.** The team's production database is the Tiger Cloud service in Audie's project (Postgres 18, Pagila v3.1.0, `nl2sql_reader` role). Every `.env`, test and `db/` script points at it.

**Alternatives.** Andrew's separate Tiger Cloud service; keeping both in step.

**Reasoning.** Audie's service already had Pagila and the reader role, and the team was using it. Two databases with different data would give different answers to the same question and break the evaluation. `db/02_load_pagila.sh` is pinned to the same Pagila version (v3.1.0) so a rebuild matches production row for row.

## October 2026: gemini-embedding-2 at 768 dimensions for retrieval

**Decision.** Embed schema descriptions and example questions with `gemini-embedding-2`, requesting 768 dimensions, stored in `vector(768)` columns in a separate `retrieval` schema. Generation stays on Ollama by default; `gemma-4-31b-it` is the free Gemini API backup.

**Alternatives.** `gemini-embedding-001`; `gemini-embedding-2-preview`; the full default size; an Ollama embedding model on Ben's server.

**Reasoning.** `gemini-embedding-2` is the current stable model and free on the API free tier; the preview could change and invalidate stored vectors. 768 dimensions was confirmed to work, keeps rows and the index small, and stays well within index limits. Embeddings from different models cannot be compared, so changing the model means re-embedding every row; each row stores `embed_model` to catch mixing. Retrieval tables live outside `public` so generated SQL cannot read them, and are written only by a separate `nl2sql_indexer` role, never the app's reader role.
