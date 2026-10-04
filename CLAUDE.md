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

- GitHub repo: `drewUTSA/Aqua`
- Ubuntu server checkout: `/srv/bank-ai` (the docker-compose project is also named `bank-ai`)
- Public site: `aqua-ai.us`, served by the frontend container on port 5173
- Local development: each person's own clone

The server runs the app with docker-compose. Code changes are made locally, pushed by a human, merged through a pull request, and pulled on the server. Nobody commits on the server: its GitHub key can only pull.

## Current stack

| Concern | Choice |
|---|---|
| Backend language | Python 3.12 (not 3.14; the ML stack does not fully support 3.14 yet) |
| API | FastAPI, served by uvicorn on 127.0.0.1:8000, reachable from outside only through nginx |
| Frontend | React 19 with Vite. Production: a static build served by nginx on port 5173, which forwards `/api` to the backend and rate-limits questions. Development: `npm run dev`, whose proxy does the same |
| Database | PostgreSQL on Tiger Cloud free service (TimescaleDB, pgvector, pgvectorscale) |
| Sample data | Pagila (Postgres port of Sakila) |
| LLM | Gemini API with the free Gemma 4 model (`gemma-4-31b-it`) by default (`LLM_PROVIDER=gemini`); Ollama (`qwen3`) on Ben's server over Tailscale as the backup. Model names read from env |
| Embeddings | `gemini-embedding-2` at 768 dimensions, stored in pgvector in the `retrieval` schema (Phase 4) |
| SQL parsing and validation | `sqlglot`, Postgres dialect |
| DB driver | `psycopg` 3 |
| Dashboards | Tableau, connected to Tiger Cloud with a read-only role |
| Tests | pytest |
| Formatting | black, default settings (ruff for linting) |
| Deployment | docker-compose on the Ubuntu server, `network_mode: host`; HTTPS is handled in front of nginx |
| Fine-tuning (later) | Open model such as Gemma with Unsloth LoRA, served by Ollama or vLLM |

Gemini cannot be fine-tuned through the free API, which is why fine-tuning targets an open model.

### Model choice

No model name is hardcoded. `LLM_PROVIDER` picks the server default (`gemini` or `ollama`), and `GEMINI_MODEL`, `OLLAMA_MODEL` and `GEMINI_EMBED_MODEL` come from `.env`, so switching models is a config change, not a code change. The default is Gemma 4 31B through the Gemini API: it is free, needs no team hardware, and the Gemini Flash models allow only about 20 free requests a day. Ollama stays as the backup and for the fine-tuned model later. The UI can pick either per question (`GET /api/models`). Keep every model out of pytest. Record each model change and its eval result in `docs/decisions.md`.

### Providers

Both providers sit behind the same `complete()` call in `nl2sql/llm.py`, so the rest of the pipeline does not change when the provider does.

- Gemini API: Gemini models get the rules as a system instruction and a JSON schema for `{"sql": ...}`. Gemma models take neither, so for them the rules go at the top of the prompt and `generate.extract_sql` reads the SQL from the code fence Gemma writes. The SDK makes at most two attempts per call, because its default retries used up free quota. Free-tier Gemma answers in roughly 20 to 80 seconds and sometimes returns HTTP 500; the pipeline reports that as a retryable outage.
- Ollama: called with a JSON schema, Qwen's recommended sampling, a fixed seed and a 16k context. `OLLAMA_THINK` turns reasoning on or off; on was more accurate in testing.

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
│   ├── requirements.txt      Runtime dependencies, including google-genai for retrieval
│   ├── requirements-ml.txt   Later: fine-tuning stack only
│   ├── main.py               FastAPI routes only; calls nl2sql.pipeline
│   ├── nl2sql/
│   │   ├── __init__.py
│   │   ├── config.py         Loads env, exposes typed settings
│   │   ├── db.py             Connection as the read-only role
│   │   ├── schema.py         Reads tables, columns, keys from the database; prompt text, allowlist, table docs
│   │   ├── llm.py            Thin model wrapper; the only file that calls a model (Gemini API, Ollama)
│   │   ├── generate.py       Builds the prompt (schema, examples, failed attempt) and asks for SQL
│   │   ├── validate.py       AST safety checks (layer 1)
│   │   ├── execute.py        Runs validated SQL in a read-only transaction
│   │   ├── summarize.py      Turns result rows into a short answer, by rule, no model call
│   │   ├── visualize.py      Picks a chart for a result (first version; Ben owns it)
│   │   ├── response.py       Answer -> the JSON the frontend renders
│   │   ├── pipeline.py       context -> generate -> validate -> execute, one retry if fixable
│   │   ├── retrieval/        Phase 4: embed.py (Gemini), store.py (offline indexer), select.py
│   │   └── querylog.py       Phase 7, not built yet: logs questions, SQL, outcome
│   └── tests/
│       ├── test_validate.py  Highest priority; adversarial SQL cases
│       ├── test_db_readonly.py Confirms writes and hidden columns fail as nl2sql_reader
│       └── test_pipeline.py  Pipeline with the LLM mocked
├── frontend/
│   ├── Dockerfile            Builds the site, then serves it with nginx
│   ├── nginx.conf            Static site, /api proxy, rate limit, security headers
│   ├── package.json          npm run dev | build | test
│   ├── vite.config.js        Dev server; proxies /api to 127.0.0.1:8000
│   ├── checks/               node --test suites (npm test)
│   ├── index.html
│   └── src/
│       ├── services/aquaClient.js  The only API entry point components use
│       ├── services/apiClient.js   Real transport: /api/query, /api/models, error mapping
│       └── services/mockClient.js  Offline stand-in, on with VITE_AQUA_USE_MOCK=true
├── db/
│   ├── README.md             How to rebuild the database from scratch
│   ├── 01_extensions.sql     vector, vectorscale
│   ├── 02_load_pagila.sh     Loads Pagila, strips OWNER TO lines
│   ├── 03_users.sql          Creates nl2sql_reader (psql prompts for the password)
│   ├── 04_retrieval.sql      retrieval schema, embedding tables, nl2sql_indexer role (Phase 4)
│   └── 05_hide_columns.sql   Takes staff.password and staff.picture from the reader (Phase 5)
├── eval/
│   ├── datasets/             pagila_v1.jsonl: 50 test and 25 train questions with gold SQL
│   ├── run_eval.py           Runs the pipeline over a dataset; --retrieval, --model, --ids, --check-gold
│   ├── metrics.py            Execution accuracy, validity rate, latency
│   └── results/              Gitignored output
├── finetune/                 Later: data prep and training scripts
└── docs/
    ├── architecture.md       How a question becomes an answer, the safety layers, deployment
    └── decisions.md          Every significant choice and why
```

Directories that only hold a `.gitkeep` are placeholders. `backend/Dockerfile` copies `main.py` and the whole `nl2sql/` package; `eval/` and `db/` stay out of the image.

## API contract

The frontend talks to the backend only through `/api`, which in production goes through nginx. Keep these shapes stable; change them only with Ben's agreement. `frontend/src/services/apiClient.js` is the one place the frontend reads these shapes.

| Route | Purpose |
|---|---|
| `GET /api/health` | Liveness for the Docker healthcheck: `status`, `database_configured`, `model`, `retrieval`. Never touches the database or model |
| `GET /api/models` | `{"models": [{"id", "name", "description"}]}`, server default first. Lists `gemini` only when `GEMINI_API_KEY` is set |
| `POST /api/query` | Body `{"question": str, "model": "ollama" or "gemini" (optional)}`. Returns `{"status": "success" or "error", "sql": str, "message": str, "tables": [...], "visualizations": [...], "kpis": [...], "error": {"code": str, "message": str, "retryable": bool} or null}` |

The shape matches what the React app renders, plus `sql` so every answer shows its query. Each table is `{"id", "title", "columns": [{"key", "label", "type"}], "rows": [{key: value}]}`, where `type` is `string`, `number`, `currency`, `percentage` or `date`; dates are ISO strings. A rejected or failed query returns HTTP 200 with `status` "error", the SQL the model wrote, and the reason, so the UI can show what was blocked. An unreachable model or database returns 503 with `retryable` true; a blank or over-long question returns 422. An unknown `model` is also a 422. Choosing `gemini` on a server with no key returns 400 with code `model_not_configured` and `retryable` false. `message` is a rule-based summary from `summarize.py`. `visualizations` and `kpis` come from `visualize.py`: a single number gives one KPI (`{"id", "label", "value", "type"}`) plus a `{"type": "kpi"}` visualization; labels with a measure give a `bar`, a date with a measure a `line`, each `{"id", "type", "title", "tableId": "result", "xKey", "yKey"}`; anything else leaves both empty. The frontend draws one x column, so a chart labelled by first and last name uses the first.

Charts use the existing `visualizations` and `kpis` fields described above; there is no separate `chart` field. Ben owns `visualize.py` and decides any change to how charts are chosen or shaped.

nginx answers 429 when one visitor sends more than 10 questions a minute (burst of 5); the client shows that as a retryable "slow down" message. The UI shows `sql` under every answer, and under refused queries as the SQL that was not run.

## Pipeline

1. Receive a question.
2. Build context: every table from `schema.py`, or with `RETRIEVAL=on` the nearest tables plus similar verified examples. If retrieval fails, fall back to every table.
3. Ask the model (Gemma 4 through the Gemini API by default, Ollama as backup) for one SQL statement.
4. Validate the SQL with `validate.py` against the schema's allowlist. On failure, never execute.
5. Execute in a read-only transaction with a row limit and timeout.
6. If step 4 or 5 failed and the error is fixable (`UnsafeQueryError.fixable`, or a database error other than a timeout), ask the model once more with the failed SQL and the error. Writes, dangerous functions and catalog access are never retried.
7. Summarize the rows, pick a chart, and return rows, summary, chart and SQL.

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

Hidden columns (`staff.password`, `staff.picture`) are refused at both layers: the validator rejects any query that names them, selects `*` from `staff`, or uses the whole row, and `db/05_hide_columns.sql` replaces the reader's table grant on `staff` with column grants. `schema.py` never shows them to the model.

The offline embedding indexer connects as `nl2sql_indexer` through `INDEXER_DATABASE_URL`. That role can write only to the `retrieval` schema and has no grants on `public`. The web app never uses it. The reader can `SELECT` from `retrieval` for similarity search, but the validator's allowlist must never include retrieval tables, so generated SQL cannot read them.

## Environment variables

```
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_MODEL=qwen3:8b
OLLAMA_THINK=true
LLM_PROVIDER=gemini
GEMINI_API_KEY=
GEMINI_MODEL=gemma-4-31b-it
GEMINI_EMBED_MODEL=gemini-embedding-2
DATABASE_URL=postgresql://nl2sql_reader:CHANGE_ME@HOST:PORT/tsdb?sslmode=require
INDEXER_DATABASE_URL=postgresql://nl2sql_indexer:CHANGE_ME@HOST:PORT/tsdb?sslmode=require
RETRIEVAL=off
```

Production sets `RETRIEVAL=on` once the index is built (see Commands). Read them only through `backend/nl2sql/config.py`. docker-compose passes `.env` to the backend container. Gemini rate limits are per Google Cloud project, so each developer uses an AI Studio key from their own project and the server at `/srv/bank-ai` uses a separate one.

## Phases

| Phase | Goal | Done when | Status |
|---|---|---|---|
| 0 | Repo scaffolding | Layout above exists, CI runs pytest and black | Open: no CI yet, and most older backend files are not black-formatted |
| 1 | Database | Pagila loaded, reader role works, write test fails as expected | Done |
| 2 | Baseline pipeline | `/api/query` returns validated SQL and rows; full schema in prompt | Done |
| 3 | Evaluation harness | Execution accuracy reported on a fixed question set | Done; results in `docs/decisions.md` |
| 4 | Retrieval layer | Relevant tables and examples retrieved per question; accuracy compared to Phase 3 | Done; retrieval measured equal or better |
| 5 | Validation hardening | Adversarial test suite passes | Done |
| 6 | React interface | Shows question, SQL, rows, and summary; served on the project domain as a production build | Done in code; live once the server is rebuilt |
| 7 | Logging and learning loop | Queries logged; good ones feed the example store | Not started |

Work one phase at a time. Do not build ahead. Frontend work can run alongside backend phases as long as it codes against the API contract above.

### Open items

Agreed but not started. Each needs its own change and a `docs/decisions.md` entry when done.

- Phase 7 logging: `db/06_logging.sql` with a `query_log` table and an insert-only `nl2sql_logger` role, `nl2sql/querylog.py`, and a way to promote checked pairs into `retrieval.example_query` as `query_log` rows.
- Tableau: `db/07_tableau_role.sql`, a read-only `tableau_reader` without the 10-second timeout and with the same hidden staff columns.
- A second, harder question set (`eval/datasets/pagila_v2.jsonl`), written before looking at model output, so the retrieval comparison rests on more than 50 questions.
- Phase 0: one commit that black-formats the backend, then a GitHub Actions workflow running pytest, black and `npm test` on every pull request.
- Modules over the size guideline: `schema.py`, `validate.py`, `retrieval/store.py`.
- Fine-tuning an open model (after Phase 7, optional).

## Conventions

- Type hints on every public Python function.
- Docstrings explain why, not what.
- No module over about 200 lines.
- No bare `except:`; catch specific exceptions.
- Format Python with black, default settings.
- Never commit `.env`, `.venv/`, `node_modules/`, database dumps, or eval results.
- Add new dependencies only when needed, and say why in the change description.
- `requirements-ml.txt` is for the fine-tuning stack only; runtime dependencies go in `requirements.txt`.
- Any significant choice gets an entry in `docs/decisions.md`: the decision, alternatives, reasoning.

## Commands

Local backend development (run from `backend/`):

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp ../.env.example ../.env       # then fill in values
python -m nl2sql.db              # connection smoke test
python -m nl2sql.schema          # print the schema the model sees
pytest
black .
uvicorn main:app --reload --port 8000
python -m nl2sql.retrieval.store # embed schema and train examples (needs INDEXER_DATABASE_URL)
```

Evaluation (run from the repo root, backend venv active; the model must be reachable):

```bash
python eval/run_eval.py --check-gold   # gold SQL only, no model calls
python eval/run_eval.py                # baseline: every table, no examples
python eval/run_eval.py --retrieval    # with retrieval, for the Phase 4 comparison
```

Local frontend development (run from `frontend/`; the backend must be running on port 8000, or set `VITE_AQUA_USE_MOCK=true` to work offline):

```bash
npm install
npm run dev
npm test
```

Server (run from `/srv/bank-ai`). After a merge, pull and rebuild; the frontend image builds the site itself:

```bash
git pull origin main
docker compose up -d --build
curl -s localhost:8000/api/health
curl -s localhost:5173/api/models
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
