# Decisions

Each entry records the decision, the alternatives considered, and why.

## October 2026: Stack and layout

**Decision.** FastAPI backend with the NL2SQL pipeline in `backend/nl2sql/`, React and Vite frontend, Gemini API (AI Studio keys) as the model, PostgreSQL on Tiger Cloud as the database, deployed with docker-compose at `/srv/bank-ai`.

**Alternatives.** Streamlit UI with code in `src/nl2sql/` (the original plan); Ollama as the primary model (the starter code).

**Reasoning.** The repo already had a working FastAPI, React, and docker-compose setup, and the frontend owner is building in React, so Streamlit would have been thrown away. Gemini's free API tier is stronger than models the server can run locally. Ollama stays available for serving the fine-tuned open model later, behind the same `llm.py` interface. The model name is read from env so the team can switch to whichever Gemini or Gemma model performs best without code changes.

## October 2026: Ollama qwen3:8b as the default model, Gemini as backup

**Superseded** by "Gemma 4 through the Gemini API as the default model" below. Kept for the record of why Ollama was chosen first.

**Decision.** Use `qwen3:8b` on Ben's Ollama server (reached over Tailscale) as the default model, with reasoning on. Keep Gemini as an optional backup behind the same `llm.py` interface. This changes the model part of the stack decision above.

**Alternatives.** Gemini (`gemini-3.6-flash`) as the only model; `qwen3:4b` (Ben's original default); `qwen2.5-coder:7b`; `qwen3:8b` with reasoning off.

**Reasoning.** Gemini's free tier turned out to allow only 20 requests per day per project for `gemini-3.6-flash`, and over several days most calls returned 503 (high demand); the SDK's automatic retries also used up quota without returning answers. That is not enough for the Phase 3 evaluation. On Ben's server there is no quota. Run against a SQLite copy of Sakila on 18 test questions, `qwen3:8b` with reasoning on got 18/18; with reasoning off it was about 13x faster but got one revenue query wrong while still running without error, so reasoning stays on by default. `qwen2.5-coder:7b` got 3 of 5 on an earlier set and `qwen3:4b` cannot turn reasoning off. Replies are constrained to `{"sql": ...}` with a JSON schema, which stopped reasoning text from leaking into the SQL.

## October 2026: Audie's Tiger Cloud service is the production database

**Decision.** The team's production database is the Tiger Cloud service in Audie's project (Postgres 18, Pagila v3.1.0, `nl2sql_reader` role). Every `.env`, test and `db/` script points at it.

**Alternatives.** Andrew's separate Tiger Cloud service; keeping both in step.

**Reasoning.** Audie's service already had Pagila and the reader role, and the team was using it. Two databases with different data would give different answers to the same question and break the evaluation. `db/02_load_pagila.sh` is pinned to the same Pagila version (v3.1.0) so a rebuild matches production row for row.

## October 2026: gemini-embedding-2 at 768 dimensions for retrieval

**Decision.** Embed schema descriptions and example questions with `gemini-embedding-2`, requesting 768 dimensions, stored in `vector(768)` columns in a separate `retrieval` schema. (When this was decided, generation stayed on Ollama; it later moved to Gemma 4, see below.)

**Alternatives.** `gemini-embedding-001`; `gemini-embedding-2-preview`; the full default size; an Ollama embedding model on Ben's server.

**Reasoning.** `gemini-embedding-2` is the current stable model and free on the API free tier; the preview could change and invalidate stored vectors. 768 dimensions was confirmed to work, keeps rows and the index small, and stays well within index limits. Embeddings from different models cannot be compared, so changing the model means re-embedding every row; each row stores `embed_model` to catch mixing. Retrieval tables live outside `public` so generated SQL cannot read them, and are written only by a separate `nl2sql_indexer` role, never the app's reader role.

## October 2026: Schema read from the database, not a file

**Decision.** `nl2sql/schema.py` reads tables, columns, keys, enum and domain types from the live database as `nl2sql_reader`, once per process, and produces the prompt text, the validator's table allowlist, and one plain-text description per table for retrieval. The temporary `pagila_schema.sql` is removed.

**Alternatives.** Keep a hand-written schema file; read `information_schema` instead of `pg_catalog`.

**Reasoning.** A file drifts from the database the first time someone changes a table. `pg_catalog` exposes what `information_schema` hides (partitions, enum labels, domains). Payment partitions are left out so the model queries the parent table. Short text columns with at most 20 distinct values list them in the prompt (category and language names), so the model matches real spellings; columns that look personal (email, phone, address, user) never list values. Write-only foreign key clauses (`ON UPDATE CASCADE`) are trimmed to save prompt space.

## October 2026: One retry when the model's SQL is fixable

**Decision.** When the validator rejects SQL for a fixable reason (parse error, a table off the allowlist, a hidden column) or the database refuses it (unknown column, type error), the pipeline asks the model once more with the failed SQL and the error. Writes, dangerous functions, catalog access and statement timeouts are not retried.

**Alternatives.** No retry; up to three retries; retry every failure.

**Reasoning.** Most first-try failures are small mistakes the model fixes when shown the error, and one retry recovers them at the cost of one extra call. Retrying a refused write would only produce a different answer to a question that must be refused, and retrying a timeout would run another slow query. `UnsafeQueryError.fixable` carries the distinction from the validator.

## October 2026: Rule-based summaries

**Decision.** `summarize.py` writes the answer text from the rows with fixed rules (one value, one row, or a count plus the first three labelled rows), not with a model call.

**Alternatives.** Ask the model to summarize the rows.

**Reasoning.** A rule-based summary can never state a number the query did not return, adds no latency (answers with reasoning already take seconds), and is fully testable. The table, chart and SQL sit right below it, so it only needs to lead. A model summary can be revisited once evaluation shows the SQL is reliable.

## October 2026: Hidden staff columns at both layers

**Decision.** `staff.password` and `staff.picture` are refused by the validator (by name, through `SELECT *` on staff, and as a whole-row value) and by the database (`db/05_hide_columns.sql` swaps the reader's table grant on `staff` for column grants). `staff_list` is revoked too.

**Alternatives.** Leave `staff` off the allowlist entirely; rely on the prompt not mentioning the columns.

**Reasoning.** Questions about staff ("who took the most payments") are reasonable, so dropping the table loses real questions. Leaving the columns out of the prompt is not access control. Two independent layers follow the project's safety rule.

## October 2026: Evaluation set and metric

**Decision.** `eval/datasets/pagila_v1.jsonl` holds 75 questions on Pagila v3.1.0: 50 `test` (15 easy, 20 medium, 15 hard) that are graded, and 25 `train` that the retrieval indexer may store as examples. Execution accuracy is reported two ways: exact (same rows, column order ignored, numbers rounded to 2 places) and lenient (the answer contains every gold column, extra columns allowed). Ranked questions also compare row order.

**Alternatives.** Compare SQL text; a public benchmark such as Spider.

**Reasoning.** Many different queries are correct, so comparing results is the standard measure. Lenient scoring counts an answer that adds a helpful total column as correct, which matches what a user would accept; exact is reported alongside so neither hides the other. Gold queries avoid ties at any LIMIT boundary and ambiguous columns (Pagila's `active` and `activebool` disagree), and every one passes the validator. Test questions are never stored as examples, or the eval would measure memory.

## October 2026: google-genai in requirements.txt

**Decision.** `google-genai` goes in `backend/requirements.txt`, so the Docker image can embed questions at query time when `RETRIEVAL=on`. `requirements-ml.txt` stays for the fine-tuning stack.

**Alternatives.** Keep it in `requirements-ml.txt` and install that in the image.

**Reasoning.** Retrieval runs inside the web app, so its client is a runtime dependency. The fine-tuning stack (PyTorch, Unsloth) is large and never needed by the web app.

## October 2026: First evaluation, baseline against retrieval

**Decision.** Turn retrieval on in production (`RETRIEVAL=on`), on the strength of the first comparison below. Re-run both modes whenever the model, prompt or dataset changes.

**Results.** `pagila_v1.jsonl`, 50 test questions, `qwen3:4b` with reasoning on (the model set in the server's `.env`), October 4, 2026, on the production Tiger Cloud service.

| | Baseline (every table, no examples) | Retrieval (nearest tables, 3 examples) |
|---|---|---|
| Execution accuracy, exact | 43/50 (86%) | 45/50 (90%) |
| Execution accuracy, lenient | 48/50 (96%) | 49/50 (98%) |
| Easy / medium, lenient | 15/15, 19/20 | 15/15, 20/20 |
| Hard, lenient | 14/15 | 14/15 |
| Rejected by the validator | 0 | 0 |
| Questions that needed the retry | 3 | 1 |
| Median seconds per question | 26.7 | 20.0 |

One baseline question (t47) was first lost to a DNS failure reaching the database, not to the model. It was rerun alone with `python eval/run_eval.py --ids t47` and passed both ways; the baseline column includes that rerun.

**What failed.** Baseline: t24 returned staff ids instead of names; t40 used a LEFT JOIN that returned films with any unrented copy rather than films never rented. Retrieval: t37 grouped actors by name, so the two different actors named Susan Davis were counted as one. Exact-only misses in both runs (t37 to t46) added a helpful count or total column, which lenient scoring accepts.

**Alternatives.** Keep the full schema; wait for a larger question set before deciding.

**Reasoning.** Retrieval was equal or better on every measure (tied on hard questions, ahead on medium ones and overall) and about 6 seconds faster per question, because the prompt is shorter. The gain is small in absolute terms (1 to 2 questions out of 50), so it is evidence, not proof; a larger or harder question set is the next step for the report. The t37 failure points at a real weakness (grouping by name instead of key), but fixing it by editing the prompt after reading test failures would tune to the test set. Any fix must be checked on questions the model has not been graded on, such as new train or held-out questions.

## October 2026: The website calls the real API; the mock stays behind a switch

**Decision.** `frontend/src/services/aquaClient.js` sends questions to `POST /api/query` and loads the model menu from `GET /api/models` through a new `apiClient.js`. Ben's mock moves to `mockClient.js` and runs only when `VITE_AQUA_USE_MOCK=true`. Every answer shows its SQL in a collapsible panel; a refused query shows the SQL that was not run.

**Alternatives.** Delete the mock; call `fetch` from the components; stream partial answers.

**Reasoning.** Keeping the transport in one module means the components Ben built needed no API-specific changes beyond the SQL panel. The mock is still useful for UI work and for `browser-review.mjs`, so it stays, off by default. The backend answers in one piece, so streaming would add complexity for no visible gain. Rate limits, bad questions, proxy error pages and network failures all become the one error shape the UI already renders, so a slow or failed answer never shows a raw error. Showing the SQL is a core requirement of the project.

## October 2026: Production frontend served by nginx, backend on localhost only

**Decision.** The frontend image builds the site and serves it with nginx on port 5173, the port the domain already pointed at. nginx forwards `/api` to the backend, waits up to 300 seconds, limits each visitor to 10 questions a minute with a burst of 5, caps request bodies at 16 KB, and sets basic security headers. The backend now binds to 127.0.0.1, so the public can reach it only through nginx.

**Alternatives.** Keep `npm run dev` in production; Caddy instead of nginx; publish the backend port directly.

**Reasoning.** The Vite dev server is not built for public traffic and rebuilds in memory on every start. Serving on 5173 means whatever routes aqua-ai.us to the server needs no change; HTTPS stays in front of nginx. Each question costs 20 to 80 seconds of model time, so without a limit one visitor could tie up the free Gemma quota or Ben's machine. With Cloudflare in front, nginx keys the limit on `CF-Connecting-IP`. Binding the backend to localhost closes the path around the rate limit. Commands on the server itself (`curl localhost:8000`, the eval) still work.

## October 2026: Retry Gemini server errors, then fall back to Ollama

**Decision.** Each Gemini call gets three attempts with a short backoff (about 2 then 4 seconds), for HTTP 500, 502, 503 and 504 only. If Gemini still fails with one of those, a 429 (spent quota) or a timeout, and `LLM_FALLBACK` is on (the default), `llm.complete()` sends the same prompt to Ollama. Bad keys and model names (400, 403, 404) never fall back. Every response now carries `model`, the model that actually answered, and the UI shows it as "Answered by". `run_eval.py` turns the fallback off unless `--fallback` is given.

**Alternatives.** Only more retries; only the fallback; switch the default back to Ollama; a paid Gemini key.

**Reasoning.** In the first full Gemma run, 14 of 50 questions (28%) failed on Google's side: 12 HTTP 500 and 2 HTTP 503, even with two quick attempts. The 36 questions Gemma did answer were all correct, so the problem is availability, not quality. More retries help with brief errors; the fallback covers long outages and a spent daily quota, which retries cannot. Retrying a 429 would only spend more quota, so it goes straight to the fallback. Configuration mistakes stay loud so they get fixed instead of silently running on Ollama. Showing the answering model keeps the fallback honest, and keeping it out of the eval by default means the scores still measure the model being evaluated.

## October 2026: Gemma 4 through the Gemini API as the default model

**Decision.** Generate SQL with `gemma-4-31b-it` on the Gemini API free tier (`LLM_PROVIDER=gemini`). Ollama (`qwen3`) on Ben's machine becomes the backup and the automatic fallback. Keep `RETRIEVAL=on`.

**Results.** `pagila_v1.jsonl`, 50 test questions, October 4, 2026, on a local copy of production (Pagila v3.1.0, same roles). Fallback off, so every Gemma number is Gemma alone. Questions lost to Google's HTTP 500 and 503 errors were rerun once with the three-attempt retry; "Outages left" are those that failed again.

| | qwen3:4b baseline | qwen3:4b retrieval | Gemma 4 baseline | Gemma 4 retrieval |
|---|---|---|---|---|
| Exact | 43/50 | 45/50 | 48/50 | 45/50 |
| Lenient | 48/50 | 49/50 | 49/50 | 48/50 |
| Wrong answers (SQL ran, result wrong) | 2 | 1 | 0 | 0 |
| Outages left | 0 | 0 | 1 | 2 |
| Hard questions, lenient | 14/15 | 14/15 | 15/15 | 13/15 (both misses are outages) |
| Median seconds | 26.7 | 20.0 | 40.9 | 47.9 |

In the first full Gemma runs, 14 of 50 questions in each mode failed on Google's side (28%) with the old two-attempt setting. In the reruns with three attempts, 3 of 28 failed again (11%); the runs were at different times, so this is not a controlled comparison.

**Alternatives.** Keep `qwen3:4b` or `qwen3:8b` on Ollama as the default; a Gemini Flash model (about 20 free requests a day); a paid key.

**Reasoning.** Gemma answered every question it reached correctly in both modes, including t37, the duplicate-name trap `qwen3:4b` failed with retrieval, and t24 and t40, which `qwen3:4b` failed without it. It is free and needs no team hardware. Its weaknesses are availability and speed: about 40 to 50 seconds per question, and Google's free tier fails often enough that the retry and Ollama fallback (entry above) are required, not optional.

Retrieval made no measurable difference to Gemma on this set: both modes got every answered question right, so the set is too easy to separate them (a ceiling). Retrieval added more exact-only misses (t38, t41, t46), where Gemma followed the examples in adding a count or total column; lenient scoring accepts those. It stays on because it helped `qwen3:4b`, which is now the fallback, and because it keeps prompts short. Separating the two for Gemma needs the harder question set listed under open items in `CLAUDE.md`.
## October 4, 2026: Google sign-in without an account database

**Decision.** Use Google Identity Services with a JavaScript credential callback. The backend verifies the Google ID token and login nonce, then issues a signed, expiring HttpOnly session cookie. Login and authenticated POST requests require Aqua CSRF tokens and the configured browser origin. Database queries additionally require an explicit account allowlist; empty allowlists deny all queries. Email entries apply only to verified Gmail or Google Workspace identities, while other Google accounts require an explicit Google `sub`. Google sign-in needs no client secret, redirect callback, or account database in this flow.

**Alternatives.** OAuth authorization-code exchange with a client secret; a new accounts database and server-side session store; granting every Google user access to the configured database.

**Reasoning.** Aqua needs identity for sign-in, not access to Google's APIs. The user requested no separate account database and wants Aqua to work over customers' existing databases. Google `sub` provides the stable identity; server configuration supplies access approval for the current single database. A successful login alone must never authorize customer data access. `google-auth[requests]` verifies Google signatures and token claims; `itsdangerous` signs time-limited session and challenge cookies. Signed cookies are readable, so they contain identity and CSRF state only, never customer database credentials or Google tokens. Logout clears the browser session; a copied cookie remains valid until expiry or secret rotation. Multi-customer database routing and durable per-session revocation require a separate design. The frontend implements Google's supported button, session restoration, logout, and authenticated queries, with fictional responses available only in explicit demo mode. Setup and integration are in `docs/google-signin.md`.

## October 4, 2026: Dedicated Aqua sign-in page

**Decision.** Show Google's sign-in controls on `/signin`, reusing Aqua's background, water sparkles, and centered animated logo. Mount the private workspace at `/` only after a live session has query access. Pending-access users stay on the sign-in page with an access recheck and sign-out action. Canonicalize these two paths with the browser History API; direct `/signin` visits need the frontend's `index.html` fallback.

**Alternatives.** Keep the login controls inside the chat screen; introduce a routing dependency for these two views.

**Reasoning.** The user requested a separate sign-in page with Aqua's existing visuals. The auth hook remains mounted across sign-in/workspace transitions, while logout, access failure, and account changes clear private workspace state and abort its queries. This needs no new dependencies or account database. At the user's request, public `/privacy` and `/terms` pages are linked from sign-in, use their supplied AQUA/Benjamin contact details, and describe the current implementation. These pages do not mount authentication, so policy access does not depend on Google or the backend. The owner should review the documents against production practices before publishing.

## October 2026: Gemini Flash-Lite as the default, then Ollama, then Gemma

**Decision.** Generate SQL with `gemini-3.5-flash-lite`. When it is out of quota, down, slow or returns an empty reply, try Ollama (`qwen3` on Ben's machine), then `gemma-4-26b-a4b-it` (`GEMINI_FALLBACK_MODELS`). Supersedes "Gemma 4 through the Gemini API as the default model". Keep the answer size rules on.

**Results.** Pagila v3.1.0 on a local copy of production, October 4, 2026, answer size rules on unless noted, fallback off so each column is one model alone. "Wrong" counts answers whose SQL ran but returned the wrong rows; outages are Google errors that survived the retries.

| | Gemma 4 31B | Gemma 4 26B-A4B | Gemini 3.5 Flash-Lite |
|---|---|---|---|
| `pagila_v1`, lenient | 42/47 (run stopped early) | 50/50 | 48/50 |
| `pagila_v1`, wrong | 0 | 0 | 2 |
| `pagila_v1`, outages | 5 | 0 (paced) | 0 |
| `pagila_size_v1`, lenient | 12/17 (rules off: 9/17, 7 wrong) | 17/17 | 16/17 |
| `pagila_size_v1`, wrong | 0 | 0 | 0 |
| Median seconds | 38.7 | 12.7 | 0.79 |

Flash-Lite's two wrong answers: t29 returned staff ids instead of names, and t50 grouped months as dates rather than month numbers (the totals were right). Its one size miss was an empty reply (a recitation stop), which now moves on to the next model.

**Alternatives.** Gemma 4 26B as the default (most accurate, about 16 times slower); `gemini-3.8-flash` (the newest Flash, about 20 free requests a day); Gemma 4 with its thinking turned to minimal (2 to 3 seconds but 3 of 5 right in a probe).

**Reasoning.** Gemma 4 thinks before answering: 600 to 4,500 hidden reasoning tokens per question, which is the 15 to 90 seconds users waited. Flash-Lite does not, takes the rules as a system instruction and replies in the JSON schema, and answered in under a second with near-Gemma accuracy. Ollama comes second because it has no quota and is the team's own model; any Ollama failure moves on, since Ben's machine may be off. Gemma 26B comes last: free with its own quota and the most accurate, but slow, and its free tier allows 16,000 input tokens a minute (about 8 questions). The answer size rules fixed every plural and tie error the 31B model made without them (7 wrong to 0). `gemini-3.8-flash` can be set as `GEMINI_MODEL` with a paid key; its free tier is too small for a site.
