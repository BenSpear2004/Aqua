"""Tests for nl2sql/display.py. The comments are the real ones from
db/financial/02_load.sql, so these also check that every bank code
comment parses."""

from nl2sql.display import Display, code_meanings, display_for, header
from nl2sql.schema import Column, Schema, Table

TRANS_TYPE = "PRIJEM = credit (money in), VYDAJ = debit (money out), VYBER = cash withdrawal."
OPERATION = (
    "VYBER KARTOU = card withdrawal, VKLAD = cash deposit, PREVOD Z UCTU = transfer in from"
    " another bank, VYBER = cash withdrawal, PREVOD NA UCET = transfer out to another bank."
)
LOAN_STATUS = (
    "A = finished, paid off; B = finished, not paid; C = running, payments on time;"
    " D = running, client in debt."
)
K_SYMBOL = (
    "Purpose: POJISTNE = insurance, SLUZBY = statement fee, UROK = interest credited,"
    " SANKC. UROK = penalty interest on a negative balance, SIPO = household bills,"
    " DUCHOD = pension, UVER = loan payment; empty or NULL = not given."
)
FREQUENCY = (
    "Statement frequency: POPLATEK MESICNE = monthly, POPLATEK TYDNE = weekly,"
    " POPLATEK PO OBRATU = after each transaction."
)


def table(name: str, columns: list[Column], comment: str = "") -> Table:
    return Table(name, tuple(columns), (), frozenset(), comment)


BANK = Schema(tables={
    "trans": table("trans", [
        Column("type", "text", True, comment=TRANS_TYPE),
        Column("operation", "text", False, comment=OPERATION),
        Column("k_symbol", "text", False, comment=K_SYMBOL),
        Column("balance", "integer", True, comment="Account balance after the transaction."),
        Column("date", "date", True),
    ], comment="Account transactions, 1993 to 1998. Amounts in Czech crowns (CZK)."),
    "loan": table("loan", [
        Column("status", "text", True, comment=LOAN_STATUS),
        Column("date", "date", True),
    ], comment="Loans granted to accounts. Amounts in Czech crowns (CZK)."),
    "account": table("account", [
        Column("frequency", "text", True, comment=FREQUENCY),
        Column("date", "date", True, comment="Date the account was opened."),
    ]),
    "district": table("district", [Column("a11", "integer", True, comment="Average salary.")]),
})


def test_codes_with_commas_in_their_meanings_parse() -> None:
    assert code_meanings(LOAN_STATUS) == {
        "A": "Finished, paid off",
        "B": "Finished, not paid",
        "C": "Running, payments on time",
        "D": "Running, client in debt",
    }


def test_multi_word_and_dotted_codes_parse_and_descriptions_are_skipped() -> None:
    meanings = code_meanings(K_SYMBOL)
    assert meanings["SANKC. UROK"] == "Penalty interest on a negative balance"
    assert meanings["UVER"] == "Loan payment"
    assert "empty or NULL" not in meanings  # lower case: a description, not a code
    assert code_meanings(OPERATION)["PREVOD Z UCTU"] == "Transfer in from another bank"


def test_values_are_translated_in_their_own_column() -> None:
    display = display_for(BANK)
    assert display.value("type", "VYDAJ") == "Debit (money out)"
    assert display.value("status", "B") == "Finished, not paid"
    assert display.value("frequency", "POPLATEK TYDNE") == "Weekly"


def test_renamed_columns_still_translate_but_single_letters_do_not() -> None:
    display = display_for(BANK)
    assert display.value("transaction_type", "PRIJEM") == "Credit (money in)"
    assert display.value("grade", "B") == "B"


def test_other_values_are_left_alone() -> None:
    display = display_for(BANK)
    assert display.value("type", "gold") == "gold"
    assert display.value("status", 3) == 3
    assert display.value("k_symbol", None) is None


def test_headers_come_from_short_comments_only() -> None:
    labels = display_for(BANK).column_labels
    assert labels["a11"] == "Average salary"
    assert labels["frequency"] == "Statement frequency"
    assert labels["k_symbol"] == "Purpose"
    assert "type" not in labels and "status" not in labels  # bare code lists
    assert "date" not in labels  # only one of the three date columns has a comment
    assert header("x" * 60) is None


def test_currency_comes_from_table_comments() -> None:
    assert display_for(BANK).currency == "CZK"
    mixed = Schema(tables={
        "a": table("a", [], comment="Amounts in Czech crowns (CZK)."),
        "b": table("b", [], comment="Amounts in euros (EUR)."),
    })
    assert display_for(mixed).currency is None


def test_a_database_without_comments_displays_as_is() -> None:
    plain = Schema(tables={"film": table("film", [Column("rating", "text", False)])})
    assert display_for(plain) == Display()


def test_rows_are_translated_cell_by_cell() -> None:
    rows = display_for(BANK).rows(["type", "amount"], [("VYDAJ", 100), ("PRIJEM", 50)])
    assert rows == [("Debit (money out)", 100), ("Credit (money in)", 50)]
