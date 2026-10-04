-- Loads the Berka bank database into public on the BANK service (not
-- the Pagila one), from the files db/financial/01_export.sh writes.
-- Run as that service's tsdbadmin, from the repo root:
--
--   docker run --rm -it -v "${PWD}:/data" -e ADMIN_URL -e PGPASSWORD postgres:18 sh -c 'psql "$ADMIN_URL" -f /data/db/financial/02_load.sql'
--
-- Then run db/03_users.sql against the same service to create
-- nl2sql_reader there; it grants SELECT on everything in public.
--
-- One transaction: a failure leaves nothing half-loaded. Refuses to run
-- if trans already exists, or if this is the Pagila service.
--
-- Table and column names match the BIRD benchmark's "financial"
-- database, so its question and SQL pairs port with little renaming.
-- Code values stay in Czech for the same reason; the column comments
-- give their English meaning. Amounts are in Czech crowns (CZK).

\set ON_ERROR_STOP on
SET search_path TO public;

SELECT to_regclass('public.trans') IS NOT NULL AS loaded,
       to_regclass('public.film') IS NOT NULL AS is_pagila \gset
\if :is_pagila
    \echo 'This is the Pagila service (public.film exists). Point ADMIN_URL at the bank service.'
    \quit
\endif
\if :loaded
    \echo 'Berka is already loaded (public.trans exists). Nothing to do.'
    \quit
\endif

BEGIN;

CREATE TABLE district (
    district_id integer PRIMARY KEY,
    a2 text NOT NULL,
    a3 text NOT NULL,
    a4 integer NOT NULL,
    a5 integer NOT NULL,
    a6 integer NOT NULL,
    a7 integer NOT NULL,
    a8 integer NOT NULL,
    a9 integer NOT NULL,
    a10 numeric(4, 1) NOT NULL,
    a11 integer NOT NULL,
    a12 numeric(4, 1),
    a13 numeric(3, 2) NOT NULL,
    a14 integer NOT NULL,
    a15 integer,
    a16 integer NOT NULL
);

CREATE TABLE account (
    account_id integer PRIMARY KEY,
    district_id integer NOT NULL,
    frequency text NOT NULL,
    date date NOT NULL
);

CREATE TABLE client (
    client_id integer PRIMARY KEY,
    gender text NOT NULL,
    birth_date date NOT NULL,
    district_id integer NOT NULL
);

CREATE TABLE disp (
    disp_id integer PRIMARY KEY,
    client_id integer NOT NULL,
    account_id integer NOT NULL,
    type text NOT NULL
);

CREATE TABLE card (
    card_id integer PRIMARY KEY,
    disp_id integer NOT NULL,
    type text NOT NULL,
    issued date NOT NULL
);

CREATE TABLE loan (
    loan_id integer PRIMARY KEY,
    account_id integer NOT NULL,
    date date NOT NULL,
    amount integer NOT NULL,
    duration integer NOT NULL,
    payments numeric(6, 2) NOT NULL,
    status text NOT NULL
);

CREATE TABLE "order" (
    order_id integer PRIMARY KEY,
    account_id integer NOT NULL,
    bank_to text NOT NULL,
    account_to integer NOT NULL,
    amount numeric(6, 1) NOT NULL,
    k_symbol text NOT NULL
);

CREATE TABLE trans (
    trans_id integer PRIMARY KEY,
    account_id integer NOT NULL,
    date date NOT NULL,
    type text NOT NULL,
    operation text,
    amount integer NOT NULL,
    balance integer NOT NULL,
    k_symbol text,
    bank text,
    account integer
);

\echo 'Loading rows'
\copy district FROM '/data/db/financial/data/district.tsv' WITH (FORMAT text, NULL 'NULL')
\copy account FROM '/data/db/financial/data/account.tsv' WITH (FORMAT text, NULL 'NULL')
\copy client FROM '/data/db/financial/data/client.tsv' WITH (FORMAT text, NULL 'NULL')
\copy disp FROM '/data/db/financial/data/disp.tsv' WITH (FORMAT text, NULL 'NULL')
\copy card FROM '/data/db/financial/data/card.tsv' WITH (FORMAT text, NULL 'NULL')
\copy loan FROM '/data/db/financial/data/loan.tsv' WITH (FORMAT text, NULL 'NULL')
\copy "order" FROM '/data/db/financial/data/order.tsv' WITH (FORMAT text, NULL 'NULL')
\copy trans FROM '/data/db/financial/data/trans.tsv' WITH (FORMAT text, NULL 'NULL')

-- Keys after the data: faster to load, and any row that breaks one
-- fails the whole transaction.
ALTER TABLE account ADD FOREIGN KEY (district_id) REFERENCES district;
ALTER TABLE client ADD FOREIGN KEY (district_id) REFERENCES district;
ALTER TABLE disp ADD FOREIGN KEY (client_id) REFERENCES client;
ALTER TABLE disp ADD FOREIGN KEY (account_id) REFERENCES account;
ALTER TABLE card ADD FOREIGN KEY (disp_id) REFERENCES disp;
ALTER TABLE loan ADD FOREIGN KEY (account_id) REFERENCES account;
ALTER TABLE "order" ADD FOREIGN KEY (account_id) REFERENCES account;
ALTER TABLE trans ADD FOREIGN KEY (account_id) REFERENCES account;

-- trans has a million rows; most questions filter it by account or date.
CREATE INDEX ON trans (account_id);
CREATE INDEX ON trans (date);

COMMENT ON TABLE account IS 'Bank accounts.';
COMMENT ON COLUMN account.frequency IS 'Statement frequency: POPLATEK MESICNE = monthly, POPLATEK TYDNE = weekly, POPLATEK PO OBRATU = after each transaction.';
COMMENT ON COLUMN account.date IS 'Date the account was opened.';
COMMENT ON TABLE client IS 'Bank customers.';
COMMENT ON TABLE disp IS 'Links clients to accounts: who owns or may use each account.';
COMMENT ON COLUMN disp.type IS 'OWNER = account owner, DISPONENT = authorized user.';
COMMENT ON TABLE card IS 'Credit cards, issued to a disposition (a client on an account).';
COMMENT ON COLUMN card.type IS 'Card type: junior, classic or gold.';
COMMENT ON TABLE loan IS 'Loans granted to accounts. Amounts in Czech crowns (CZK).';
COMMENT ON COLUMN loan.duration IS 'Loan length in months.';
COMMENT ON COLUMN loan.payments IS 'Monthly payment.';
COMMENT ON COLUMN loan.status IS 'A = finished, paid off; B = finished, not paid; C = running, payments on time; D = running, client in debt.';
COMMENT ON TABLE "order" IS 'Standing payment orders from an account. Amounts in Czech crowns (CZK).';
COMMENT ON COLUMN "order".bank_to IS 'Recipient bank code.';
COMMENT ON COLUMN "order".account_to IS 'Recipient account number.';
COMMENT ON COLUMN "order".k_symbol IS 'Purpose: POJISTNE = insurance, SIPO = household bills, LEASING = leasing, UVER = loan payment; empty = not given.';
COMMENT ON TABLE trans IS 'Account transactions, 1993 to 1998. Amounts in Czech crowns (CZK).';
COMMENT ON COLUMN trans.type IS 'PRIJEM = credit (money in), VYDAJ = debit (money out), VYBER = cash withdrawal.';
COMMENT ON COLUMN trans.operation IS 'VYBER KARTOU = card withdrawal, VKLAD = cash deposit, PREVOD Z UCTU = transfer in from another bank, VYBER = cash withdrawal, PREVOD NA UCET = transfer out to another bank.';
COMMENT ON COLUMN trans.balance IS 'Account balance after the transaction.';
COMMENT ON COLUMN trans.k_symbol IS 'Purpose: POJISTNE = insurance, SLUZBY = statement fee, UROK = interest credited, SANKC. UROK = penalty interest on a negative balance, SIPO = household bills, DUCHOD = pension, UVER = loan payment; empty or NULL = not given.';
COMMENT ON COLUMN trans.bank IS 'Partner bank code, for transfers.';
COMMENT ON COLUMN trans.account IS 'Partner account number, for transfers.';
COMMENT ON TABLE district IS 'Demographics for each district.';
COMMENT ON COLUMN district.a2 IS 'District name.';
COMMENT ON COLUMN district.a3 IS 'Region.';
COMMENT ON COLUMN district.a4 IS 'Number of inhabitants.';
COMMENT ON COLUMN district.a5 IS 'Municipalities with fewer than 500 inhabitants.';
COMMENT ON COLUMN district.a6 IS 'Municipalities with 500 to 1999 inhabitants.';
COMMENT ON COLUMN district.a7 IS 'Municipalities with 2000 to 9999 inhabitants.';
COMMENT ON COLUMN district.a8 IS 'Municipalities with 10000 or more inhabitants.';
COMMENT ON COLUMN district.a9 IS 'Number of cities.';
COMMENT ON COLUMN district.a10 IS 'Share of urban inhabitants, percent.';
COMMENT ON COLUMN district.a11 IS 'Average salary.';
COMMENT ON COLUMN district.a12 IS 'Unemployment rate in 1995, percent.';
COMMENT ON COLUMN district.a13 IS 'Unemployment rate in 1996, percent.';
COMMENT ON COLUMN district.a14 IS 'Entrepreneurs per 1000 inhabitants.';
COMMENT ON COLUMN district.a15 IS 'Crimes committed in 1995.';
COMMENT ON COLUMN district.a16 IS 'Crimes committed in 1996.';

COMMIT;

ANALYZE district, account, client, disp, card, loan, "order", trans;

\echo 'Row counts (expected: district 77, account 4500, client 5369, disp 5369, card 892, loan 682, order 6471, trans 1056320):'
SELECT 'district' AS table_name, count(*) FROM district
UNION ALL SELECT 'account', count(*) FROM account
UNION ALL SELECT 'client', count(*) FROM client
UNION ALL SELECT 'disp', count(*) FROM disp
UNION ALL SELECT 'card', count(*) FROM card
UNION ALL SELECT 'loan', count(*) FROM loan
UNION ALL SELECT 'order', count(*) FROM "order"
UNION ALL SELECT 'trans', count(*) FROM trans;

\echo 'Size (a free service turns read-only at 750 MiB):'
SELECT pg_size_pretty(pg_database_size(current_database())) AS database_size;
