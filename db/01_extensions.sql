-- Extensions for the Aqua database on Tiger Cloud.
-- Run as tsdbadmin: psql "$ADMIN_URL" -v ON_ERROR_STOP=1 -f db/01_extensions.sql
-- Safe to re-run.

-- pgvector: vector column type for schema and example-query embeddings (Phase 4).
CREATE EXTENSION IF NOT EXISTS vector;

-- pgvectorscale: diskann index for embeddings over pgvector's 2000-dimension HNSW limit.
CREATE EXTENSION IF NOT EXISTS vectorscale CASCADE;

-- Show what is installed so the run output doubles as a check.
SELECT extname, extversion
FROM pg_extension
WHERE extname IN ('vector', 'vectorscale', 'timescaledb')
ORDER BY extname;
