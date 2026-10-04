-- Takes staff.password and staff.picture away from nl2sql_reader.
--
-- Layer 2 for the hidden columns: the validator rejects queries that
-- name them (layer 1), and this makes the database refuse them too,
-- including through SELECT * or row_to_json(staff). The reader keeps
-- every other staff column, so "which staff member took the most
-- payments" still works.
--
-- Run as tsdbadmin with psql, from the repo root, after 03_users.sql:
--
--   psql "$ADMIN_URL" -v ON_ERROR_STOP=1 -f db/05_hide_columns.sql
--
-- Safe to run again. Run it again after any re-run of 03_users.sql,
-- because 03 grants SELECT on every table, staff included.

BEGIN;

-- Postgres checks table-level grants first, so the table grant must go
-- before column grants can limit anything.
REVOKE SELECT ON public.staff FROM nl2sql_reader;
GRANT SELECT (staff_id, first_name, last_name, address_id, email, store_id,
              active, username, last_update)
    ON public.staff TO nl2sql_reader;

-- Same for the view that exposes staff details.
REVOKE SELECT ON public.staff_list FROM nl2sql_reader;

COMMIT;

-- Show the result: the reader's staff columns, password and picture absent.
SELECT column_name
FROM information_schema.column_privileges
WHERE table_schema = 'public' AND table_name = 'staff'
  AND grantee = 'nl2sql_reader' AND privilege_type = 'SELECT'
ORDER BY column_name;
