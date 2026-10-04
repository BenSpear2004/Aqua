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

## October 2026: Baseline on qwen3:8b

**Decision.** Recommend switching the server's `OLLAMA_MODEL` from `qwen3:4b` to `qwen3:8b`, the code default, once its speed is checked on the server.

**Results.** `pagila_v1.jsonl`, 50 test questions, baseline mode (every table, no examples), `qwen3:8b` with reasoning on, October 4, 2026, on the production Tiger Cloud service and Ben's Ollama server.

| | qwen3:8b baseline |
|---|---|
| Execution accuracy, exact | 40/50 (80%) |
| Execution accuracy, lenient | 50/50 (100%) |
| Easy / medium, lenient | 15/15, 20/20 |
| Hard, lenient | 15/15 |
| Rejected by the validator | 0 |
| Questions that needed the retry | 2 |
| Median seconds per question | 20.3 |

**What failed.** Nothing on lenient scoring. Both retries (t04, t35) were ILIKE on the `rating` enum, which Postgres refuses; after the prompt fix, a rerun of the five rating questions took one attempt each (t04 59 s to 13 s, t35 62 s to 15 s). The 10 exact-only misses added an id or the count the query ranked by. t24 and t40, which `qwen3:4b` lost in its baseline, were both answered correctly.

**Alternatives.** Stay on `qwen3:4b` with retrieval.

**Reasoning.** Without retrieval, `qwen3:8b` matched or beat `qwen3:4b` with retrieval on every lenient measure and was about as fast in this run. Its lower exact score comes from adding helpful columns, not from wrong answers. Speed on the server under real use still needs checking, since this run sent one question at a time. Retrieval on `qwen3:8b` is the next comparison.
