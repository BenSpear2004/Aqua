# Bank database (Berka)

The Czech bank data lives on its own Tiger Cloud service, separate from the Pagila one. A human runs these steps as that service's `tsdbadmin`; the app and coding agents never do.

## Source

The Berka dataset (PKDD'99 Discovery Challenge): anonymized data from a Czech bank, 1993 to 1998, with accounts, clients, transactions, loans and cards. Exported from the [CTU Prague Relational Learning Repository](https://relational.fel.cvut.cz/dataset/Financial). Cite the repository paper (Motl and Schulte, 2015) when using it in the report.

Table and column names match the `financial` database in the BIRD benchmark, so its question and SQL pairs port with little renaming.

## Steps

Run from the repo root in PowerShell. Use the bank service's connection details, never the Pagila service's.

```powershell
$env:ADMIN_URL = "postgresql://tsdbadmin@HOST:PORT/tsdb?sslmode=require"
$env:PGPASSWORD = Read-Host "Bank service tsdbadmin password"
```

| Step | Command | What it does |
|---|---|---|
| 1 | `docker run --rm -v "${PWD}:/data" mariadb:11 sh /data/db/financial/01_export.sh` | Exports the 8 tables from CTU into `db/financial/data/` (gitignored) |
| 2 | `docker run --rm -it -v "${PWD}:/data" -e ADMIN_URL -e PGPASSWORD postgres:18 sh -c 'psql "$ADMIN_URL" -f /data/db/financial/02_load.sql'` | Creates the tables in `public`, loads the rows in one transaction, adds keys, indexes and English column comments |
| 3 | `docker run --rm -it -v "${PWD}:/data" -e ADMIN_URL -e PGPASSWORD postgres:18 sh -c 'psql "$ADMIN_URL" -f /data/db/03_users.sql'` | Creates `nl2sql_reader` on this service; prompts for its password |

Then run `Remove-Item Env:ADMIN_URL, Env:PGPASSWORD`.

Step 2 refuses to run if the tables already exist, or if `ADMIN_URL` points at the Pagila service.

Expected row counts: district 77, account 4500, client 5369, disp 5369, card 892, loan 682, order 6471, trans 1056320. The database is about 125 MB of the free service's 750 MiB.

## Notes for writing questions and SQL

- Code values are in Czech (`PRIJEM`, `VYDAJ`, `POPLATEK MESICNE`, loan status `A` to `D`). The column comments in `02_load.sql` give their English meaning.
- District facts are in columns `a2` to `a16`; see the comments for what each holds (for example `a11` is average salary).
- `order` is a reserved word, so queries must write it as `"order"`.
- In `trans.k_symbol`, a blank purpose is a single space (`' '`), not an empty string, while `order.k_symbol` uses an empty string. Postgres treats `' '` and `''` as different values, unlike MySQL.
- Amounts are in Czech crowns (CZK).
