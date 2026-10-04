#!/bin/sh
# Exports the Berka (PKDD'99 Czech Financial) bank database from the CTU
# Prague Relational Learning Repository into tab-separated files for
# db/financial/02_load.sql.
#
# Runs inside the mariadb:11 image, so no MariaDB client is needed on
# the host. From the repo root (PowerShell or bash):
#
#   docker run --rm -v "${PWD}:/data" mariadb:11 sh /data/db/financial/01_export.sh
#
# The guest login is published by CTU at
# relational.fel.cvut.cz/dataset/Financial. Their server has no TLS,
# which is acceptable for public data behind a public password.
#
# Columns are listed explicitly, in the order 02 loads them, so a change
# on CTU's side fails loudly instead of loading values into the wrong
# columns. Batch mode writes NULL as the word NULL and escapes tabs,
# newlines and backslashes the way Postgres COPY reads them.

set -eu

OUT=/data/db/financial/data
mkdir -p "$OUT"

export_table() {
    echo "Exporting $1"
    mariadb --skip-ssl -h relational.fel.cvut.cz -P 3306 \
        -u guest -pctu-relational --batch --skip-column-names financial \
        -e "SELECT $2 FROM \`$1\`" > "$OUT/$1.tsv"
}

export_table district "district_id, A2, A3, A4, A5, A6, A7, A8, A9, A10, A11, A12, A13, A14, A15, A16"
export_table account "account_id, district_id, frequency, date"
export_table client "client_id, gender, birth_date, district_id"
export_table disp "disp_id, client_id, account_id, type"
export_table card "card_id, disp_id, type, issued"
export_table loan "loan_id, account_id, date, amount, duration, payments, status"
export_table order "order_id, account_id, bank_to, account_to, amount, k_symbol"
export_table trans "trans_id, account_id, date, type, operation, amount, balance, k_symbol, bank, account"

echo "Rows per file:"
wc -l "$OUT"/*.tsv
