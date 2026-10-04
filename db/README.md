# Database setup

How to build the Aqua database on Tiger Cloud from an empty service. A human runs these as `tsdbadmin`; the app and coding agents never do.

## Before you start

- `psql` installed (`sudo apt install -y postgresql-client` on Ubuntu)
- The `tsdbadmin` connection string from the Tiger Cloud console, kept in a password manager
- Run everything from the repo root (`/srv/bank-ai` on the server)

Export the admin connection for this shell only. Never put it in `.env`.

```bash
export ADMIN_URL='postgresql://tsdbadmin:PASSWORD@HOST:PORT/tsdb?sslmode=require'
```

## Steps, in order

| Step | Command | What it does |
|---|---|---|
| 1 | `psql "$ADMIN_URL" -v ON_ERROR_STOP=1 -f db/01_extensions.sql` | Enables pgvector and pgvectorscale |
| 2 | `bash db/02_load_pagila.sh` | Loads Pagila schema and data, prints row counts |
| 3 | `psql "$ADMIN_URL" -f db/03_users.sql` | Creates `nl2sql_reader`; prompts for its password |
| 4 | `psql "$ADMIN_URL" -f db/04_retrieval.sql` | Creates the `retrieval` schema and embedding tables, and the `nl2sql_indexer` role; prompts for its password |

| 5 | `psql "$ADMIN_URL" -v ON_ERROR_STOP=1 -f db/05_hide_columns.sql` | Takes `staff.password` and `staff.picture` away from `nl2sql_reader`; prints the staff columns it keeps |

Order matters: step 3 grants `SELECT` on the tables step 2 creates, and step 5 narrows the staff part of that grant. Run step 5 again after any re-run of step 3.

After step 4, fill the retrieval tables from `backend/` with `python -m nl2sql.retrieval.store`. It needs `INDEXER_DATABASE_URL` and `GEMINI_API_KEY` in `.env`, embeds only what changed, and is safe to run again.

Step 2 refuses to run if `public.film` already exists. To reload from scratch, drop the Pagila objects first (ask the team before doing that on the shared service).

Expected row counts after step 2: actor 200, film 1000, customer 599, store 2, rental 16044, payment 16049. Payments run from 2022-01-23 to 2022-07-27. These match the production service.

## Check the reader role

```bash
export DATABASE_URL='postgresql://nl2sql_reader:READER_PASSWORD@HOST:PORT/tsdb?sslmode=require'
psql "$DATABASE_URL" -c "SELECT title FROM film LIMIT 3;"
psql "$DATABASE_URL" -c "INSERT INTO actor (first_name, last_name) VALUES ('x', 'y');"
psql "$DATABASE_URL" -c "SET default_transaction_read_only = off" -c "INSERT INTO actor (first_name, last_name) VALUES ('x', 'y');"
```

The select returns rows. The first insert fails with `read-only transaction`. The second fails with `permission denied for table actor`, which proves the grants block writes even when the session turns read-only mode off.

When finished, run `unset ADMIN_URL`.

## Notes on the Pagila load

`02_load_pagila.sh` downloads Pagila v3.1.0 from [devrimgunduz/pagila](https://github.com/devrimgunduz/pagila), pinned by commit, and removes lines that need a superuser or a `postgres` role, which Tiger Cloud does not give us. Tested on Postgres 17 as a non-superuser that owns the database, which matches `tsdbadmin`.

Do not move to Pagila v4.x without a team decision. It has different rows (999 customers, 500 stores, payments through 2026), so the eval set's gold answers would all change. It also needs Postgres 18.

To check which version a database holds, run `SELECT count(*) FROM store;`. v3.x returns 2; newer snapshots return 500.
