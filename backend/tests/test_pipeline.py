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
from nl2sql.generate import Example, Generation
from nl2sql.llm import LLMError
from nl2sql.pipeline import Context, answer_question
from nl2sql.schema import Column, Schema, Table

SETTINGS = Settings()
FILM = Table(
    name="film",
    columns=(Column("film_id", "integer", True), Column("title", "text", True)),
    constraints=("PRIMARY KEY (film_id)",),
    references=frozenset(),
)
SCHEMA = Schema(tables={"film": FILM})
OK = QueryResult(
    sql="SELECT COUNT(*) AS films FROM film LIMIT 1000",
    columns=["films"],
    rows=[(1000,)],
    truncated=False,
)


def fake_model(monkeypatch: pytest.MonkeyPatch, *replies: str) -> list[dict]:
    """The model answers with each reply in turn; returns what it was sent."""
    calls: list[dict] = []
    queue = list(replies)

    def fake_generate(
        question,
        schema,
        settings,
        client=None,
        examples=(),
        previous=None,
        size=None,
    ):
        calls.append(
            {
                "question": question,
                "schema": schema,
                "examples": examples,
                "previous": previous,
                "size": size,
            }
        )
        return Generation(
            sql=queue.pop(0), thinking="I should count films.", model="test-model"
        )

    monkeypatch.setattr(pipeline, "generate_sql", fake_generate)
    return calls


def fake_database(monkeypatch: pytest.MonkeyPatch, *outcomes) -> list[str]:
    """execute returns or raises each outcome in turn; returns the SQL it got."""
    calls: list[str] = []
    queue = list(outcomes)

    def fake_execute(query, settings, max_rows):
        calls.append(query.sql(dialect="postgres"))
        outcome = queue.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(pipeline, "execute", fake_execute)
    return calls


def test_success_returns_rows_and_provenance(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_model(monkeypatch, "SELECT count(*) AS films FROM film")
    fake_database(monkeypatch, OK)

    answer = answer_question("How many films are there?", SETTINGS, SCHEMA)

    assert answer.error is None and answer.error_code is None
    assert (
        answer.sql == "SELECT COUNT(*) AS films FROM film LIMIT 1000"
    )  # the SQL that ran
    assert answer.rows == [(1000,)]
    assert answer.thinking == "I should count films."
    assert answer.model == "test-model"
    assert answer.attempts == 1 and answer.used_retrieval is False


def test_without_retrieval_the_model_sees_every_table(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = fake_model(monkeypatch, "SELECT title FROM film")
    fake_database(monkeypatch, OK)
    answer_question("q", SETTINGS, SCHEMA)
    assert calls[0]["schema"] == SCHEMA.to_prompt()
    assert calls[0]["examples"] == ()


def test_rejected_writes_are_never_executed_or_retried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = fake_model(monkeypatch, "DELETE FROM film WHERE film_id = 1")
    executed = fake_database(monkeypatch)

    answer = answer_question("Delete film 1.", SETTINGS, SCHEMA)

    assert executed == [] and len(calls) == 1
    assert answer.error_code == "rejected" and "Only SELECT" in answer.error
    assert (
        answer.sql == "DELETE FROM film WHERE film_id = 1"
    )  # shown so the user can see why
    assert answer.attempts == 1


def test_tables_off_the_allowlist_are_rejected_then_retried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = fake_model(
        monkeypatch,
        "SELECT first_name FROM customer",
        "SELECT count(*) AS films FROM film",
    )
    executed = fake_database(monkeypatch, OK)

    answer = answer_question("q", SETTINGS, SCHEMA)

    assert len(executed) == 1 and "customer" not in executed[0]
    assert calls[1]["previous"].sql == "SELECT first_name FROM customer"
    assert "not allowed: customer" in calls[1]["previous"].error
    assert answer.error is None and answer.attempts == 2


def test_database_refusal_gets_one_retry_with_the_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = fake_model(monkeypatch, "SELECT nope FROM film", "SELECT title FROM film")
    fake_database(monkeypatch, QueryError('column "nope" does not exist'), OK)

    answer = answer_question("q", SETTINGS, SCHEMA)

    assert 'column "nope" does not exist' in calls[1]["previous"].error
    assert answer.error is None and answer.attempts == 2


def test_second_failure_is_reported_with_the_last_sql(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_model(monkeypatch, "SELECT nope FROM film", "SELECT still_nope FROM film")
    fake_database(
        monkeypatch,
        QueryError("first"),
        QueryError('column "still_nope" does not exist'),
    )

    answer = answer_question("q", SETTINGS, SCHEMA)

    assert answer.error_code == "query_failed"
    assert answer.sql == "SELECT still_nope FROM film"
    assert "still_nope" in answer.error and answer.attempts == 2


def test_timeouts_are_not_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = fake_model(monkeypatch, "SELECT title FROM film")
    fake_database(
        monkeypatch, QueryError("canceling statement due to statement timeout")
    )

    answer = answer_question("q", SETTINGS, SCHEMA)

    assert len(calls) == 1 and answer.error_code == "query_failed"


def test_max_rows_is_passed_through(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_model(monkeypatch, "SELECT title FROM film")
    seen = {}

    def fake_execute(query, settings, max_rows):
        seen["max_rows"] = max_rows
        return QueryResult(sql="x", columns=[], rows=[], truncated=False)

    monkeypatch.setattr(pipeline, "execute", fake_execute)
    answer_question("q", SETTINGS, SCHEMA, max_rows=50)
    assert seen["max_rows"] == 50


class FakeRetriever:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.asked: list[str] = []

    def select(self, question: str, schema: Schema) -> Context:
        self.asked.append(question)
        if self.fail:
            raise RuntimeError("embedding quota exhausted")
        return Context(
            schema_text="CREATE TABLE film (film_id integer);",
            examples=(Example("How many films?", "SELECT count(*) FROM film"),),
            tables=("film",),
        )


def test_retrieved_context_and_examples_reach_the_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = fake_model(monkeypatch, "SELECT count(*) AS films FROM film")
    fake_database(monkeypatch, OK)
    retriever = FakeRetriever()

    answer = answer_question("Count the films", SETTINGS, SCHEMA, retriever=retriever)

    assert retriever.asked == ["Count the films"]
    assert calls[0]["schema"] == "CREATE TABLE film (film_id integer);"
    assert calls[0]["examples"][0].question == "How many films?"
    assert answer.used_retrieval is True


def test_retrieval_failure_falls_back_to_the_full_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = fake_model(monkeypatch, "SELECT count(*) AS films FROM film")
    fake_database(monkeypatch, OK)

    answer = answer_question("q", SETTINGS, SCHEMA, retriever=FakeRetriever(fail=True))

    assert calls[0]["schema"] == SCHEMA.to_prompt()
    assert answer.error is None and answer.used_retrieval is False


@pytest.mark.parametrize(
    "error",
    [
        LLMError("Cannot connect to Ollama"),
        DatabaseError("Could not connect to the database"),
    ],
)
def test_service_outages_are_raised_not_hidden(
    monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    """The API turns these into server errors, so they must not become Answers."""
    if isinstance(error, LLMError):

        def broken_generate(*args, **kwargs):
            raise error

        monkeypatch.setattr(pipeline, "generate_sql", broken_generate)
    else:
        fake_model(monkeypatch, "SELECT title FROM film")
        fake_database(monkeypatch, error)

    with pytest.raises(type(error)):
        answer_question("q", SETTINGS, SCHEMA)


def test_empty_question_is_refused() -> None:
    with pytest.raises(ValueError):
        answer_question("   ", SETTINGS, SCHEMA)


# ---- answer size (answer_size.py) ----


def test_plural_ranking_questions_ask_the_model_for_ten_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = fake_model(monkeypatch, "SELECT title FROM film")
    fake_database(monkeypatch, OK)

    answer = answer_question("What are the least popular films?", SETTINGS, SCHEMA)

    assert "Return the top 10" in calls[0]["size"]
    assert answer.size.kind == "list" and answer.size.rows == 10


def test_singular_ranking_questions_ask_for_ties(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = fake_model(monkeypatch, "SELECT title FROM film")
    fake_database(monkeypatch, OK)
    answer_question("What is the least popular film?", SETTINGS, SCHEMA)
    assert "every tied row" in calls[0]["size"]


def test_questions_without_ranking_get_no_size_line(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = fake_model(monkeypatch, "SELECT count(*) AS films FROM film")
    fake_database(monkeypatch, OK)
    answer_question("How many films are there?", SETTINGS, SCHEMA)
    assert calls[0]["size"] is None


def test_size_rules_can_be_switched_off(monkeypatch: pytest.MonkeyPatch) -> None:
    from dataclasses import replace

    calls = fake_model(monkeypatch, "SELECT title FROM film")
    fake_database(monkeypatch, OK)
    answer = answer_question(
        "What are the least popular films?",
        replace(SETTINGS, answer_size_rules=False),
        SCHEMA,
    )
    assert calls[0]["size"] is None and answer.size.kind == "open"


def test_the_size_line_survives_a_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = fake_model(monkeypatch, "SELECT nope FROM film", "SELECT title FROM film")
    fake_database(monkeypatch, QueryError('column "nope" does not exist'), OK)
    answer_question("top 5 films", SETTINGS, SCHEMA)
    assert calls[0]["size"] == calls[1]["size"]
    assert "exactly 5 rows" in calls[1]["size"]
