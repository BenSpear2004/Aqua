#!/usr/bin/env bash
# Loads the Pagila sample database into Tiger Cloud.
#
# Run as tsdbadmin, from the repo root, after db/01_extensions.sql and
# before db/03_users.sql (03 grants SELECT on the tables this creates):
#
#   bash db/02_load_pagila.sh
#
# Needs ADMIN_URL exported in the shell. Refuses to run if Pagila is
# already loaded, so it cannot double-load or clobber data.
#
# Pinned to Pagila v3.1.0, the version on the team's production service.
# Every rebuild must load the same data, because the eval set's gold
# answers are computed from it. Newer Pagila (v4.x) has different rows.
#
# Pagila is a pg_dump made on a server where everything belongs to the
# postgres superuser. tsdbadmin is not a superuser, so these lines are
# removed before loading:
#   OWNER TO postgres              - ownership stays with tsdbadmin
#   GRANT/REVOKE ON SCHEMA public  - Pagila opens public to every role;
#                                    we keep Postgres's safer default

set -euo pipefail

PAGILA_TAG="pagila-v3.1.0"
PAGILA_COMMIT="fef9675714cfba1756df4719b5e36075a7ddf90e"
BASE="https://raw.githubusercontent.com/devrimgunduz/pagila/${PAGILA_COMMIT}"

: "${ADMIN_URL:?Export ADMIN_URL (the tsdbadmin connection string) first.}"

if [[ -n "$(psql "$ADMIN_URL" -tAc "SELECT to_regclass('public.film')")" ]]; then
    echo "Pagila is already loaded (public.film exists). Nothing to do." >&2
    exit 1
fi

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

for file in pagila-schema.sql pagila-data.sql; do
    echo "Downloading ${file} (${PAGILA_TAG})"
    curl -fsSL "${BASE}/${file}" -o "${tmp}/${file}"
    sed -E -i \
        -e '/OWNER TO /d' \
        -e '/^(GRANT|REVOKE) .* ON SCHEMA public /d' \
        "${tmp}/${file}"
done

# One transaction for schema and data, so a failure leaves nothing half-loaded.
echo "Loading schema and data"
psql "$ADMIN_URL" -v ON_ERROR_STOP=1 --single-transaction -q -o /dev/null \
    -f "${tmp}/pagila-schema.sql" \
    -f "${tmp}/pagila-data.sql"

# The schema creates this view WITH NO DATA; reading it errors until refreshed.
psql "$ADMIN_URL" -v ON_ERROR_STOP=1 -q \
    -c "REFRESH MATERIALIZED VIEW public.rental_by_category;"

echo "Row counts:"
psql "$ADMIN_URL" -v ON_ERROR_STOP=1 -c "
SELECT 'actor' AS table_name, count(*) FROM public.actor
UNION ALL SELECT 'film', count(*) FROM public.film
UNION ALL SELECT 'customer', count(*) FROM public.customer
UNION ALL SELECT 'store', count(*) FROM public.store
UNION ALL SELECT 'rental', count(*) FROM public.rental
UNION ALL SELECT 'payment', count(*) FROM public.payment;"
