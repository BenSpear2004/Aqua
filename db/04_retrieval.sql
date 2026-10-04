-- Retrieval store for Phase 4: embedded schema descriptions and example
-- question/SQL pairs, so each prompt gets only the relevant tables and
-- the most similar worked examples.
--
-- Run as tsdbadmin with psql, from the repo root, after 01 to 03:
--
--   psql "$ADMIN_URL" -f db/04_retrieval.sql
--
-- It asks for a password for nl2sql_indexer, the role the offline
-- indexing script uses to write embeddings. Safe to run again, for
-- example to change that password.
--
-- Why a separate schema: 03_users.sql grants nl2sql_reader SELECT on
-- every table in public, and generated SQL must never read these
-- tables. Keeping them in `retrieval` means user queries cannot reach
-- them by accident, while the app's own retrieval code still can.
--
-- Embeddings: gemini-embedding-2 at 768 dimensions (docs/decisions.md).
-- Changing the model or size means a new column type and re-embedding
-- every row, so embed_model is stored per row to catch mixing.

\set ON_ERROR_STOP on

CREATE SCHEMA IF NOT EXISTS retrieval;

-- One row per Pagila table or view. `content` is the text that was
-- embedded (name, columns, keys, a sentence on what the table holds),
-- and is also what goes into the prompt when the table is retrieved.
-- content_hash lets the indexer skip tables whose text has not changed.
CREATE TABLE IF NOT EXISTS retrieval.schema_doc (
    table_name   text PRIMARY KEY,
    content      text NOT NULL,
    content_hash text NOT NULL,
    embedding    vector(768) NOT NULL,
    embed_model  text NOT NULL,
    updated_at   timestamptz NOT NULL DEFAULT now()
);

-- Worked examples shown to the model as few-shot context.
--   source   - where the pair came from. Eval *test* questions must
--              never be stored here, or the eval measures memory, not
--              accuracy.
--   verified - a person checked the SQL returns the right answer.
--              Only verified rows are retrieved by default.
CREATE TABLE IF NOT EXISTS retrieval.example_query (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    question    text NOT NULL UNIQUE,
    sql         text NOT NULL,
    tables      text[] NOT NULL DEFAULT '{}',
    source      text NOT NULL CHECK (source IN ('seed', 'eval_train', 'query_log')),
    verified    boolean NOT NULL DEFAULT false,
    embedding   vector(768) NOT NULL,
    embed_model text NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now()
);

-- Approximate nearest-neighbour index (pgvectorscale) for when the
-- example store grows from query logs. schema_doc has about 25 rows, so
-- a plain scan is faster there and it gets no index.
CREATE INDEX IF NOT EXISTS example_query_embedding_idx
    ON retrieval.example_query USING diskann (embedding vector_cosine_ops);

-- Reader: the app looks up similar rows at question time. Read only.
GRANT USAGE ON SCHEMA retrieval TO nl2sql_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA retrieval TO nl2sql_reader;

-- Indexer: the offline script that embeds and stores rows. It can
-- write to retrieval and nothing else; it gets no grants on public.
\prompt 'Password for nl2sql_indexer: ' indexer_password

SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'nl2sql_indexer') AS role_exists \gset
\if :role_exists
    ALTER ROLE nl2sql_indexer WITH LOGIN PASSWORD :'indexer_password';
\else
    CREATE ROLE nl2sql_indexer WITH LOGIN PASSWORD :'indexer_password';
\endif

SELECT current_database() AS dbname \gset
GRANT CONNECT ON DATABASE :"dbname" TO nl2sql_indexer;
GRANT USAGE ON SCHEMA retrieval TO nl2sql_indexer;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA retrieval TO nl2sql_indexer;
-- Indexing a few hundred rows is quick; stop anything stuck.
ALTER ROLE nl2sql_indexer SET statement_timeout = '60s';

-- Show the result so the run output doubles as a check.
SELECT table_name, privilege_type, grantee
FROM information_schema.role_table_grants
WHERE table_schema = 'retrieval'
  AND grantee IN ('nl2sql_reader', 'nl2sql_indexer')
ORDER BY table_name, grantee, privilege_type;
