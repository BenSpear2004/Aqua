"""Tests for nl2sql/pipeline.py, with the model mocked.

generate_sql and execute are replaced with stand-ins, so these need no
model and no database. The real validate_sql runs, because the point is
to check that rejected SQL never reaches execute.
"""

import pytest

from nl2sql import pipeline
from nl2sql.config import Settings
from nl2sql.db import DatabaseError
from nl2sql.execute import QueryError, QueryResult
from nl2sql.generate import Generation
from nl2sql.llm import LLMError
from nl2sql.pipeline import answer_question, load_default_schema

SETTINGS = Settings()
SCHEMA = "CREATE TABLE film (film_id integer, title text);"


def fake_model(monkeypatch: pytest.MonkeyPatch, sql: str) -> None:
    def fake_generate(question, schema, settings, client=None):
        return Generation(sql=sql, thinking="I should count films.", model="test-model")

    monkeypatch.setattr(pipeline, "generate_sql", fake_generate)


def fake_database(monkeypatch: pytest.MonkeyPatch, result=None, error=None) -> list:
    """Replace execute; returns the list of queries it was given."""
    calls = []

    def fake_execute(query, settings, max_rows):
        calls.append(query.sql(dialect="postgres"))
        if error is not None:
            raise error
        return result

    monkeypatch.setattr(pipeline, "execute", fake_execute)
    return calls


def test_success_returns_rows_and_provenance(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_model(monkeypatch, "SELECT count(*) AS films FROM film")
    fake_database(monkeypatch, QueryResult(
        sql="SELECT COUNT(*) AS films FROM film LIMIT 1000", columns=["films"], rows=[(1000,)], truncated=False,
    ))

    answer = answer_question("How many films are there?", SETTINGS, SCHEMA)

    assert answer.error is None and answer.error_code is None
    assert answer.sql == "SELECT COUNT(*) AS films FROM film LIMIT 1000"  # the SQL that ran
    assert answer.columns == ["films"]
    assert answer.rows == [(1000,)]
    assert answer.thinking == "I should count films."
    assert answer.model == "test-model"


def test_rejected_sql_is_never_executed(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_model(monkeypatch, "DELETE FROM film WHERE rating = 'R'")
    calls = fake_database(monkeypatch)

    answer = answer_question("Delete all films rated R.", SETTINGS, SCHEMA)

    assert calls == []
    assert answer.error_code == "rejected"
    assert "Only SELECT" in answer.error
    assert answer.sql == "DELETE FROM film WHERE rating = 'R'"  # shown so the user can see why
    assert answer.rows == []


def test_database_refusal_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_model(monkeypatch, "SELECT nope FROM film")
    fake_database(monkeypatch, error=QueryError('column "nope" does not exist'))

    answer = answer_question("q", SETTINGS, SCHEMA)

    assert answer.error_code == "query_failed"
    assert "does not exist" in answer.error
    assert answer.sql == "SELECT nope FROM film"


def test_max_rows_is_passed_through(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_model(monkeypatch, "SELECT title FROM film")
    seen = {}

    def fake_execute(query, settings, max_rows):
        seen["max_rows"] = max_rows
        return QueryResult(sql="x", columns=[], rows=[], truncated=False)

    monkeypatch.setattr(pipeline, "execute", fake_execute)
    answer_question("q", SETTINGS, SCHEMA, max_rows=50)
    assert seen["max_rows"] == 50


@pytest.mark.parametrize(
    "error",
    [LLMError("Cannot connect to Ollama"), DatabaseError("Could not connect to the database")],
)
def test_service_outages_are_raised_not_hidden(monkeypatch: pytest.MonkeyPatch, error: Exception) -> None:
    """The API turns these into server errors, so they must not become Answers."""
    if isinstance(error, LLMError):
        def broken_generate(*args, **kwargs):
            raise error

        monkeypatch.setattr(pipeline, "generate_sql", broken_generate)
    else:
        fake_model(monkeypatch, "SELECT 1")
        fake_database(monkeypatch, error=error)

    with pytest.raises(type(error)):
        answer_question("q", SETTINGS, SCHEMA)


def test_empty_question_is_refused() -> None:
    with pytest.raises(ValueError):
        answer_question("   ", SETTINGS, SCHEMA)


def test_default_schema_is_the_pagila_tables_without_comments() -> None:
    schema = load_default_schema()
    assert schema.count("CREATE TABLE") == 15
    assert "--" not in schema
    assert "password" not in schema
