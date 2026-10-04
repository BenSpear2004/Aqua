# Aqua project guide

Instructions for coding agents working in this repository. Read this file before making changes.

## What this project is

A natural-language-to-SQL app. A user asks a question in plain English and gets back the result rows, a short readable summary, and the exact SQL that produced them.

UTSA Senior Design capstone, Fall 2026 to Spring 2027. Professor: John Heaps. Budget is $0, so every dependency must be free tier or open source.

The research contribution is the retrieval layer (what context the model sees) and the validation layer (proving generated SQL is safe before it runs). The LLM call itself is one small function. Fine-tuning an open model and comparing it against Gemini is a later phase.

## Team

| Person | Owns |
|---|---|
| Andrew Velazquez | Database and table setup (`db/`), backend |
| Audie Ploe | Tableau dashboards, backend |
| Benjamin Spear | Domain and hosting, frontend (`frontend/`) |

## Where the code lives

- GitHub repo: `aqua`
- Ubuntu server checkout: `/srv/bank-ai` (the docker-compose project is also named `bank-ai`)
- Local development: each person's own clone

The server runs the app with docker-compose. Code changes are made locally, pushed by a human, and pulled on the server.

## Current stack

| Concern | Choice |
|---|---|
| Backend language | Python 3.12 (not 3.14; the ML stack does not fully support 3.14 yet) |
| API | FastAPI, served by uvicorn on port 8000 |
| Frontend | React 19 with Vite, port 5173, proxies `/api` to the backend |
| Database | PostgreSQL on Tiger Cloud free service (TimescaleDB, pgvector, pgvectorscale) |
| Sample data | Pagila (Postgres port of Sakila) |
| LLM | Gemini API via the `google-genai` SDK, keys from Google AI Studio, model name read from env |
| Embeddings | Gemini embeddings stored in pgvector (Phase 4) |
| SQL parsing and validation | `sqlglot`, Postgres dialect |
| DB driver | `psycopg` 3 |
| Dashboards | Tableau, connected to Tiger Cloud with a read-only role |
| Tests | pytest |
| Formatting | black, default settings (ruff for linting) |
| Deployment | docker-compose on the Ubuntu server, `network_mode: host` |
| Fine-tuning (later) | Open model such as Gemma with Unsloth LoRA, served by Ollama or vLLM |

Gemini cannot be fine-tuned through the free API, which is why fine-tuning targets an open model.

### Model choice

No model name is hardcoded. `GEMINI_MODEL` and `GEMINI_EMBED_MODEL` come from `.env`, so switching models is a config change, not a code change. Use the strongest model the free AI Studio quota allows for evaluation runs, and a cheaper Flash or Gemma model for day-to-day development so quota is not burned. List the models a key can use with `client.models.list()`. Record each model change and its eval result in `docs/decisions.md`.

### Ollama

`backend/main.py` currently calls Ollama. That is starter code. Phase 2 replaces it with the Gemini pipeline. Ollama comes back only in the fine-tuning phase, behind the same `llm.py` interface, so the rest of the pipeline does not change when the model provider does.

## Repository layout

```
aqua/                         (checked out at /srv/bank-ai on the server)
├── CLAUDE.md                 This file
├── README.md                 Human setup guide
├── .env.example              Variable names only, no real values
├── .gitignore
├── docker-compose.yml        backend + frontend services
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt      Core dependencies, Phases 0 to 3
│   ├── requirements-ml.txt   Retrieval and fine-tuning stack, Phase 4 onward
│   ├── main.py               FastAPI routes only; calls nl2sql.pipeline
│   ├── nl2sql/
│   │   ├── __init__.py
│   │   ├── config.py         Loads env, exposes typed settings
│   │   ├── db.py             Connection as the read-only role
│   │   ├── schema.py         Introspects tables, columns, keys into text for prompts
│   │   ├── llm.py            Thin model wrapper; the only file that imports google-genai
│   │   ├── prompt.py         Builds the prompt from question + schema + examples
│   │   ├── validate.py       AST safety checks (layer 1)
│   │   ├── execute.py        Runs validated SQL in a read-only transaction
│   │   ├── summarize.py      Turns result rows into a short answer
│   │   ├── pipeline.py       question -> prompt -> SQL -> validate -> execute -> summarize
│   │   ├── retrieval/        Phase 4: embed.py, store.py, select.py
│   │   └── querylog.py       Phase 7: logs questions, SQL, outcome
│   └── tests/
│       ├── test_validate.py  Highest priority; adversarial SQL cases
│       ├── test_db_readonly.py Confirms writes fail as nl2sql_reader
│       └── test_pipeline.py  Pipeline with the LLM mocked
├── frontend/
│   ├── Dockerfile
│   ├── package.json
│   ├── vite.config.js        Proxies /api to 127.0.0.1:8000
│   ├── index.html
│   └── src/
├── db/
│   ├── README.md             How to rebuild the database from scratch
│   ├── 01_extensions.sql     vector, vectorscale
│   ├── 02_load_pagila.sh     Loads Pagila, strips OWNER TO lines
│   ├── 03_users.sql          Creates nl2sql_reader (password passed as a psql variable)
│   └── 04_retrieval.sql      Example-query and schema-embedding tables (Phase 4)
├── eval/
│   ├── datasets/             Question and gold-SQL pairs (JSONL)
│   ├── run_eval.py           Runs the pipeline over a dataset
│   ├── metrics.py            Execution accuracy, validity rate, latency
│   └── results/              Gitignored output
├── finetune/                 Later: data prep and training scripts
└── docs/
    ├── architecture.md
    └── decisions.md          Every significant choice and why
```

Directories that only hold a `.gitkeep` are placeholders. When `backend/nl2sql/` is added, `backend/Dockerfile` must copy it into the image along with `main.py`.

## API contract

The frontend talks to the backend only through `/api`. Keep these shapes stable; change them only with Ben's agreement.

| Route | Purpose |
|---|---|
| `GET /api/health` | Liveness and whether the database and model are configured |
| `POST /api/query` | Body `{"question": str}`. Returns `{"sql": str, "columns": [str], "rows": [[...]], "summary": str, "error": str or null}` |

When validation fails, `/api/query` returns HTTP 200 with `error` set and `rows` empty, so the UI can show the rejected SQL and the reason. Server faults (database down, model unreachable) use 5xx codes.

## Pipeline

1. Receive a question.
2. Build context: schema text (Phase 2), later the retrieved relevant tables and similar example queries (Phase 4).
3. Ask Gemini for one SQL statement.
4. Validate the SQL with `validate.py`. On failure, return the reason; never execute.
5. Execute in a read-only transaction with a row limit and timeout.
6. Summarize the rows.
7. Return rows, summary, and the SQL.

## Safety rules (non-negotiable)

Two independent layers. Both must exist; neither replaces the other.

Layer 1, `validate.py`, parses with sqlglot and rejects anything that is not exactly:

- one statement
- a `SELECT`, optionally with `WITH` CTEs that are themselves read-only
- touching only tables on the allowlist (Pagila tables; never the retrieval or query-log tables)
- free of DML, DDL, `COPY`, `SET`, `CALL`, `DO`, transaction control, and data-modifying CTEs
- free of dangerous functions (for example `pg_sleep`, `pg_read_file`, `pg_read_binary_file`, `lo_import`, `lo_export`, `dblink`, `set_config`)

Validation walks the AST. Never validate by string matching for keywords like `DROP`.

Execution also enforces a `LIMIT` (add one if missing, cap it if too large).

Layer 2 is the database role. The app connects only as `nl2sql_reader`, which has `SELECT` only, `default_transaction_read_only = on`, and `statement_timeout = 10s`. The `SELECT`-only grant is what actually blocks writes, because a session can turn the read-only default off; layer 1 rejecting `SET` covers that path.

The admin account (`tsdbadmin`) must never appear in app code, `.env`, docker-compose, or tests. It is used only by a human running `db/` scripts with `ADMIN_URL` exported in their shell. Tableau also connects with a read-only role, never the admin account.

## Environment variables

```
GEMINI_API_KEY=
GEMINI_MODEL=
GEMINI_EMBED_MODEL=
DATABASE_URL=postgresql://nl2sql_reader:CHANGE_ME@HOST:PORT/tsdb?sslmode=require
```

Read them only through `backend/nl2sql/config.py`. docker-compose passes `.env` to the backend container. Gemini rate limits are per Google Cloud project, so each developer uses an AI Studio key from their own project and the server at `/srv/bank-ai` uses a separate one.

## Phases

| Phase | Goal | Done when |
|---|---|---|
| 0 | Repo scaffolding | Layout above exists, CI runs pytest and black |
| 1 | Database | Pagila loaded, reader role works, write test fails as expected |
| 2 | Baseline pipeline | `/api/query` returns validated SQL and rows; full schema in prompt; Ollama call removed |
| 3 | Evaluation harness | Execution accuracy reported on a fixed question set |
| 4 | Retrieval layer | Relevant tables and examples retrieved per question; accuracy compared to Phase 3 |
| 5 | Validation hardening | Adversarial test suite passes |
| 6 | React interface | Shows question, SQL, rows, and summary; served from `/srv/bank-ai` on the project domain as a production Vite build, not the dev server |
| 7 | Logging and learning loop | Queries logged; good ones feed the example store |

Work one phase at a time. Do not build ahead. Frontend work can run alongside backend phases as long as it codes against the API contract above.

## Conventions

- Type hints on every public Python function.
- Docstrings explain why, not what.
- No module over about 200 lines.
- No bare `except:`; catch specific exceptions.
- Format Python with black, default settings.
- Never commit `.env`, `.venv/`, `node_modules/`, database dumps, or eval results.
- Add new dependencies only when needed, and say why in the change description.
- Do not install `requirements-ml.txt` before Phase 4.
- Any significant choice gets an entry in `docs/decisions.md`: the decision, alternatives, reasoning.

## Commands

Local backend development (run from `backend/`):

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp ../.env.example ../.env       # then fill in values
python -m nl2sql.db              # connection smoke test
pytest
black .
uvicorn main:app --reload --port 8000
```

Local frontend development (run from `frontend/`):

```bash
npm install
npm run dev
```

Server (run from `/srv/bank-ai`):

```bash
git pull
docker compose up -d --build
docker compose logs -f backend
```

## Rules for agents

- Never commit, push, or open pull requests. Make code changes only and leave them uncommitted for a human to review.
- Do not create, modify, or delete Tiger Cloud services. Use database tools in read-only mode.
- Do not run DDL or write queries against the shared database. Schema changes go in `db/*.sql` for a human to apply.
- Write or update tests in `backend/tests/test_validate.py` before changing `validate.py`.
- Mock the LLM in unit tests; do not spend API quota in pytest.
- Do not change the `/api` contract without updating this file and telling the frontend owner.
- If a task conflicts with this file, stop and ask.
