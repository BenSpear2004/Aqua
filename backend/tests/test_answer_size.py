"""Tests for nl2sql/answer_size.py: how many rows a question asks for."""

import pytest

from nl2sql.answer_size import DEFAULT_LIST_ROWS, AnswerSize, answer_size

CASES = [
    # Plural ranking with no number: the default list.
    ("What are the least popular movies?", "list", DEFAULT_LIST_ROWS),
    ("least popular movies", "list", DEFAULT_LIST_ROWS),
    ("Show me the most rented films", "list", DEFAULT_LIST_ROWS),
    ("Which customers have spent the most?", "list", DEFAULT_LIST_ROWS),
    ("Who are the top customers?", "list", DEFAULT_LIST_ROWS),
    ("Which customers spent the most money?", "list", DEFAULT_LIST_ROWS),
    ("cheapest films", "list", DEFAULT_LIST_ROWS),
    # Singular ranking: first place and its ties.
    ("What is the least popular movie?", "single", None),
    ("the least popular movie", "single", None),
    ("Who spent the most?", "single", None),
    ("Which actor has appeared in the most films?", "single", None),
    ("Which film was rented the most?", "single", None),
    ("What is the longest film?", "single", None),
    # An explicit number, in digits or words, anywhere it reads as a count.
    ("What are the top 3 film categories by total payment revenue?", "count", 3),
    ("Which two customers have rented the most films?", "count", 2),
    ("Show 25 customers", "count", 25),
    ("list the 50 least popular movies", "count", 50),
    ("top ten actors", "count", 10),
    ("What are the five cheapest films?", "count", 5),
    # Ranking within each group.
    ("What is the most popular film in each category?", "per_group", 1),
    ("Top 3 films per category", "per_group", 3),
    ("Which films are the most rented in each store?", "per_group", DEFAULT_LIST_ROWS),
    # Everything.
    ("List all film categories", "all", None),
    ("Show every customer in London", "all", None),
    # No ranking: filters and counts are not rankings, and numbers in them
    # are values, not row counts.
    ("How many films are there?", "open", None),
    ("Which countries have more than 30 customers?", "open", None),
    ("Which films are longer than 180 minutes?", "open", None),
    ("How many payments were made in March 2022?", "open", None),
    ("How many inventory copies does store 2 hold?", "open", None),
    ("For each store, how many rentals were made from its inventory?", "open", None),
    ("Which films rated PG-13 are less than 60 minutes?", "open", None),
]


@pytest.mark.parametrize(("question", "kind", "rows"), CASES)
def test_answer_size(question: str, kind: str, rows: int | None) -> None:
    assert answer_size(question) == AnswerSize(kind, rows)


def test_absurd_counts_are_ignored() -> None:
    """A number above the 1,000-row cap is not a row count."""
    assert answer_size("top 5000 films").kind != "count"


@pytest.mark.parametrize(
    ("size", "fragment"),
    [
        (AnswerSize("count", 5), "exactly 5 rows"),
        (AnswerSize("list", 10), "Return the top 10"),
        (AnswerSize("single"), "RANK() OVER"),
        (AnswerSize("per_group", 1), "PARTITION BY"),
        (AnswerSize("per_group", 3), "ranks 1 to 3"),
        (AnswerSize("all"), "do not add a LIMIT"),
    ],
)
def test_every_kind_but_open_has_an_instruction(
    size: AnswerSize, fragment: str
) -> None:
    assert fragment in size.instruction


def test_open_questions_add_nothing_to_the_prompt() -> None:
    assert AnswerSize("open").instruction is None


def test_single_answers_never_ask_for_limit_1() -> None:
    assert "Do not use LIMIT 1" in AnswerSize("single").instruction


@pytest.mark.parametrize(
    "question",
    [
        "How many different films have been rented at least once?",
        "Which customers rented at most 12 films?",
    ],
)
def test_at_least_and_at_most_are_filters_not_rankings(question: str) -> None:
    assert answer_size(question).kind == "open"


def test_single_instruction_separates_a_value_from_the_rows_that_reach_it() -> None:
    """'The highest replacement cost' wants MAX(); 'which film' wants ties."""
    text = AnswerSize("single").instruction
    assert "MAX or MIN" in text and "every tied row" in text


@pytest.mark.parametrize(
    "question",
    [
        "give me a list of the top spenders",
        "list the top spenders",
        "top spenders",
        "show me the biggest customers",
        "who are our best customers",
        "list customers by total spend",
        "show films ranked by number of rentals",
        "rank accounts by balance",
    ],
)
def test_lists_without_a_number_default_to_the_top_ten(question: str) -> None:
    assert answer_size(question) == AnswerSize("list", DEFAULT_LIST_ROWS)


@pytest.mark.parametrize(
    "question",
    [
        "show rentals by store",
        "How many films by category?",
        "list payments made by Mary Smith",
    ],
)
def test_groupings_and_filters_by_something_are_not_rankings(question: str) -> None:
    assert answer_size(question).kind == "open"


def test_lists_are_ordered_from_highest_unless_asking_for_the_lowest() -> None:
    text = AnswerSize("list", 10).instruction
    assert "from highest to lowest" in text and "lowest first only" in text
