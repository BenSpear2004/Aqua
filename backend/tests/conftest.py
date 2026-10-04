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


@pytest.fixture(autouse=True)
def no_answer_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """API tests ask the same placeholder question many times with
    different stand-in pipelines; a cached answer would leak between
    them. Tests of the cache itself install their own."""
    try:
        import main
    except ImportError:
        return
    from nl2sql.cache import AnswerCache

    monkeypatch.setattr(main, "ANSWER_CACHE", AnswerCache(0))


@pytest.fixture(autouse=True)
def no_real_gemini(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unit tests must never spend API quota (CLAUDE.md). Any code path
    that builds a real Gemini client, for example a fallback step a test
    forgot to stub, fails loudly instead of calling Google."""
    from google import genai

    def refuse(*args, **kwargs):
        raise AssertionError("a test tried to create a real Gemini client")

    monkeypatch.setattr(genai, "Client", refuse)
