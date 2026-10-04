-- Creates (or updates) nl2sql_app, the read-only role the backend uses
-- to query the database. Never point the app at the admin login.
--
-- Run it as the admin user (tsdbadmin on Tiger Cloud) with psql. It asks
-- for the new role's password, so the password is never stored in this
-- file or in your command history. From the repo root, with TIGER_URL
-- and PGPASSWORD set to the admin connection:
--
--   docker run --rm -it -v "${PWD}:/data" -e TIGER_URL -e PGPASSWORD postgres:18 sh -c 'psql "$TIGER_URL" -f /data/backend/db/readonly_role.sql'
--
-- Safe to run again, for example to change the password.

\set ON_ERROR_STOP on
\prompt 'Password for nl2sql_app: ' app_password

SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'nl2sql_app') AS role_exists \gset
\if :role_exists
    ALTER ROLE nl2sql_app WITH LOGIN PASSWORD :'app_password';
\else
    CREATE ROLE nl2sql_app WITH LOGIN PASSWORD :'app_password';
\endif

-- Reading: connect to this database and SELECT from tables in public.
-- No INSERT, UPDATE, DELETE or ownership is granted, which is what
-- actually stops writes.
SELECT current_database() AS dbname \gset
GRANT CONNECT ON DATABASE :"dbname" TO nl2sql_app;
GRANT USAGE ON SCHEMA public TO nl2sql_app;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO nl2sql_app;
-- Tables the admin creates later are readable too.
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO nl2sql_app;

-- Pagila's setup script ends with GRANT ALL ON SCHEMA public TO PUBLIC,
-- which lets every role create tables in public. Take that back.
REVOKE CREATE ON SCHEMA public FROM PUBLIC;

-- Extra layers. A session could switch read-only mode off itself, so
-- the missing grants above remain the real guarantee.
ALTER ROLE nl2sql_app SET default_transaction_read_only = on;
-- Cancel any single query that runs longer than 10 seconds.
ALTER ROLE nl2sql_app SET statement_timeout = '10s';
