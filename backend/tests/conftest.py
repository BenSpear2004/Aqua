"""Shared fixtures for the tests that use the real database.

DATABASE_URL decides which Tiger service those tests run against: the
bank (Berka) or Pagila. Tests written for the other one skip instead of
failing, so the suite passes against either, including while teammates
move their .env to the bank.
"""

import pytest

from nl2sql.config import load_settings
from nl2sql.db import connect


@pytest.fixture(scope="session")
def live_database() -> str:
    """'bank' or 'pagila'. Skips when DATABASE_URL is not set.

    An unreachable database is an error, not a skip, so an outage is
    never mistaken for a pass.
    """
    settings = load_settings()
    if not settings.database_url:
        pytest.skip("DATABASE_URL is not set; this test needs the real database")
    with connect(settings) as conn:
        bank, pagila = conn.execute(
            "SELECT to_regclass('public.trans') IS NOT NULL,"
            " to_regclass('public.film') IS NOT NULL"
        ).fetchone()
    if bank:
        return "bank"
    if pagila:
        return "pagila"
    pytest.fail("DATABASE_URL points at a database with neither the bank nor the Pagila tables")


@pytest.fixture
def on_bank(live_database: str) -> None:
    if live_database != "bank":
        pytest.skip("needs the bank service; DATABASE_URL points at Pagila")


@pytest.fixture
def on_pagila(live_database: str) -> None:
    if live_database != "pagila":
        pytest.skip("needs the Pagila service; DATABASE_URL points at the bank")
