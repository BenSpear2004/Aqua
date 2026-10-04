# Architecture

How Aqua turns a plain-English question into rows, a summary, a chart and the SQL that produced them, and what keeps that safe. Reasons for each choice are in `decisions.md`; working rules for contributors are in `CLAUDE.md`.

## The path of one question

```
Browser (aqua-ai.us)
   |  HTTPS, terminated in front of the server
   v
nginx  :5173  (frontend container)
   |  static site; /api/* forwarded; 10 questions a minute per visitor
   v
FastAPI  127.0.0.1:8000  (backend container, main.py)
   |
   v
pipeline.answer_question
   |-- context:  schema.py (every table)  or  retrieval/select.py (nearest tables + examples)
   |-- generate.py + llm.py  ->  Gemini API (Gemma 4, default)  or  Ollama (backup)
   |-- validate.py           ->  refuse anything unsafe; never executed
   |-- execute.py            ->  Tiger Cloud Postgres as nl2sql_reader, read-only, row limit
   |-- one retry with the error, if the failure is fixable
   v
response.py  ->  summarize.py (text)  +  visualize.py (chart or KPI)  ->  JSON
```

Both containers use the host's network. Only nginx listens on an outside-facing port; the backend binds to 127.0.0.1, so every public request passes nginx's rate limit and size limit first.

## Pipeline, step by step

| Step | Module | What it does |
|---|---|---|
| Receive | `main.py`, `cache.py` | Returns a cached answer if the same question was answered with the same model and settings in the last 10 minutes (successes only). Otherwise Validates the request body (1 to 2,000 characters, known model id) and picks the provider: the request's `model`, or `LLM_PROVIDER` |
| Schema | `schema.py` | Reads tables, columns, keys, enum and domain types from the database once per process, as the read-only role. Hides `staff.password` and `staff.picture`. Lists real values for short text columns (category names, languages) |
| Context | `pipeline.py`, `retrieval/select.py` | Without retrieval: every table. With `RETRIEVAL=on`: embeds the question, takes the four nearest table descriptions, the tables the three nearest worked examples used, and any table that links two chosen ones. Falls back to every table if retrieval fails |
| Answer size | `answer_size.py` | Reads the question with plain rules: a number gives that many rows, a plural with no number the top 10, a singular first place plus every tie, "in each" the same per group, "all" no limit. Adds one line to the prompt; nothing for questions without a ranking |
| Generate | `generate.py`, `llm.py` | Builds the prompt (schema, examples, question, answer size, and on a retry the failed SQL and error) and asks the model for one SELECT |
| Validate | `validate.py` | Parses with sqlglot and walks the syntax tree. Rejects anything but one read-only SELECT on allowed tables. Marks each rejection fixable or not |
| Execute | `execute.py`, `db.py` | Runs the parsed query with a row limit (1,000) in a read-only transaction as `nl2sql_reader` |
| Retry | `pipeline.py` | If validation or execution failed for a fixable reason, asks the model once more with the error. Writes, dangerous functions, catalog access and timeouts are never retried |
| Respond | `response.py`, `summarize.py`, `visualize.py` | Converts values to JSON, writes a rule-based summary, picks a bar chart, line chart or KPI, and includes the SQL |

## Models

| Use | Model | Where |
|---|---|---|
| SQL generation (default) | `gemini-3.5-flash-lite` | Gemini API, free tier; about 1 second |
| SQL generation (first fallback) | `gemma-4-26b-a4b-it` | Gemini API, free tier with its own quota; 15 to 90 seconds |
| SQL generation (last fallback) | `qwen3:8b` or `qwen3:4b` | Ollama on Ben's machine, over Tailscale |
| Embeddings for retrieval | `gemini-embedding-2`, 768 dimensions | Gemini API, free tier |

`llm.complete()` is the only function that calls a generation model. Gemma models on the API accept neither a system instruction nor a JSON schema, so for them the rules go at the top of the prompt and the SQL is read from the code fence Gemma writes. Gemma 4 thinks before answering (600 to 4,500 hidden reasoning tokens per question), which is why it takes 15 to 90 seconds; Flash-Lite does not, and answers in about a second. The free tier also returns HTTP 500, 503 and 429 at times (28% of questions in one Gemma run). Two defences, both in `llm.py`:

1. Each Gemini call gets three attempts with a short backoff (about 2 then 4 seconds), for server errors only. A spent quota (429) is not retried, because retrying spends more.
2. If a model still fails with an outage, a spent quota or a timeout, and `LLM_FALLBACK` is on, the same prompt goes to each of `GEMINI_FALLBACK_MODELS` in turn, then to Ollama, which also gets the system rules and JSON schema Gemma cannot take. Bad keys and model names never fall back, so configuration mistakes stay visible.

Every answer carries the model that actually answered, and the UI shows it, so a fallback is never hidden. Only when both providers fail does the user see "not reachable right now" with a retry button. The eval turns the fallback off unless `--fallback` is given, so its scores measure the chosen model.

## Safety

Two independent layers; either one alone would stop a write.

| Layer | Where | What it stops |
|---|---|---|
| 1. Validator | `validate.py` | More than one statement; anything but SELECT; DML and DDL anywhere, including inside WITH; SET, COPY, CALL, DO, transaction control; dangerous functions (`pg_sleep`, file readers, `dblink`, `postgres_fdw`, sequence and lock functions); system catalogs and the `retrieval` schema; tables off the allowlist; the hidden staff columns by name, through `SELECT *`, or as a whole row |
| 2. Database role | `db/03_users.sql`, `db/05_hide_columns.sql` | `nl2sql_reader` has SELECT only, read-only transactions by default, a 10-second statement timeout, and column grants on `staff` that leave out the hidden columns |

Validation parses; it never searches the text for keywords, so `WHERE title = 'DROP ZONE'` passes and a write hidden after a comment does not.

### Database roles

| Role | Used by | Can do |
|---|---|---|
| `tsdbadmin` | A person running `db/` scripts, from their shell only | Everything; never in `.env`, code or tests |
| `nl2sql_reader` | The web app, eval, `schema.py` | SELECT on Pagila tables (staff without password and picture) and on `retrieval` for similarity search |
| `nl2sql_indexer` | `python -m nl2sql.retrieval.store`, run by a person | Write to the `retrieval` schema only; no access to Pagila |

## Data

- **Pagila v3.1.0** in `public`: 15 base tables, 16,044 rentals, 16,049 payments from January to July 2022. `db/02_load_pagila.sh` is pinned to this version, so a rebuild matches production row for row.
- **`retrieval` schema** (`db/04_retrieval.sql`): `schema_doc`, one embedded description per table, and `example_query`, verified question and SQL pairs with a diskann vector index. Only training questions are stored, never graded ones.

## Evaluation

`eval/run_eval.py` runs the pipeline over `eval/datasets/pagila_v1.jsonl` (50 graded test questions, 25 training questions) and compares the rows each answer returns with the rows of a hand-written correct query. It reports exact and lenient execution accuracy, how often SQL was rejected or failed, retries and latency. Options choose retrieval, the provider, or single questions. Results go to `eval/results/` (not committed); the numbers that settle a decision go into `decisions.md`.

## Frontend

React and Vite. `src/services/aquaClient.js` is the only module components call: it sends questions to `POST /api/query`, loads the model menu from `GET /api/models`, and turns HTTP errors, rate limits and network failures into the one response shape the components render. `VITE_AQUA_USE_MOCK=true` swaps in the offline mock for UI work. Every answer shows its SQL in a collapsible panel; a refused query shows the SQL that was not run.

## Deployment

| Piece | How |
|---|---|
| Server | Ubuntu, checkout at `/srv/bank-ai`, `docker compose up -d --build` |
| Frontend container | Multi-stage build: `npm ci` and `vite build`, then `nginx:alpine` serving `dist/` on 5173 |
| Backend container | `python:3.12-slim`, uvicorn on 127.0.0.1:8000, settings from `.env` |
| HTTPS and the domain | Handled in front of nginx; nginx keys its rate limit on Cloudflare's `CF-Connecting-IP` when present |
| Health | `GET /api/health` never touches the database or model, so a slow dependency cannot mark the container unhealthy |
| Updates | Change code locally, merge a pull request, then `git pull` and rebuild on the server. The server's GitHub key can only pull |

### Timeouts and limits

| Limit | Value | Set in |
|---|---|---|
| Question length | 2,000 characters | `main.py` |
| Request body | 16 KB | `nginx.conf` |
| Questions per visitor | 10 a minute, burst of 5 | `nginx.conf` |
| Wait for an answer | 300 seconds | `nginx.conf` |
| Model call | 180 seconds; Gemini gets 3 attempts on server errors, then Ollama | `llm.py` |
| SQL statement | 10 seconds | `nl2sql_reader` role |
| Rows returned | 1,000 | `execute.py` |
| Rows for a plural ranking with no number | 10 | `answer_size.py` |
| Reused answer lifetime | 600 seconds (`ANSWER_CACHE_SECONDS`) | `cache.py` |

### What a failure looks like

| Failure | HTTP | User sees | Retry offered |
|---|---|---|---|
| Model wrote unsafe SQL | 200 | Why it was refused, and the SQL that was not run | No |
| Database refused the SQL twice | 200 | The database's reason and the SQL | No |
| Gemini down, Ollama up | 200 | A normal answer, marked "Answered by" the Ollama model | Not needed |
| Model or database unreachable | 503 | "Not reachable right now" | Yes |
| Too many questions | 429 | "Wait a moment" | Yes |
| Question empty or too long | 422 | "Keep it under 2,000 characters" | No |

## Not built yet

Query logging and the learning loop (Phase 7), a Tableau role, a second question set, CI, and fine-tuning. See "Open items" in `CLAUDE.md`.
