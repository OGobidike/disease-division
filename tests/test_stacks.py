"""The real stacks and the real golden set, as committed."""

from collections import Counter
from pathlib import Path

import pytest

from disease_division.golden import check, load_questions
from disease_division.kb import CONTROL_NUMBER, load_documents, split_passages

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def documents():
    return load_documents(ROOT / "kb")


@pytest.fixture(scope="module")
def questions():
    return load_questions(ROOT / "evals" / "questions.toml")


def test_the_golden_set_passes_every_check(questions, documents):
    assert check(questions, documents) == []


def test_the_golden_set_has_the_planned_mix(questions):
    assert Counter(q.kind for q in questions) == {
        "answerable": 40,
        "staff_only": 8,
        "no_answer": 12,
    }


def test_every_section_of_a_staff_page_carries_its_control_number(documents):
    for document in documents:
        numbers = set(CONTROL_NUMBER.findall(document.body))
        if document.visibility == "public":
            assert not numbers, document.id
            continue
        assert len(numbers) == 1, document.id
        (number,) = numbers
        for passage in split_passages(document):
            assert number in passage.text, passage.id


def test_no_two_staff_pages_share_a_control_number(documents):
    owners = [n for d in documents for n in set(CONTROL_NUMBER.findall(d.body))]
    assert len(owners) == len(set(owners)) == 5


def test_no_page_names_a_real_hotel(documents):
    # Rockview is a real hotel in Abuja. The partner hotel's name is invented.
    assert not any("Rockview" in d.body or "Rockview" in d.title for d in documents)


def test_some_true_answers_come_from_outside_sources(questions, documents):
    # Defenses that distrust the web and email will cost these answers. Measuring that cost
    # is part of the experiment, so the golden set must include them.
    outside = {d.id for d in documents if d.source != "staff"}
    assert sum(q.doc in outside for q in questions if q.kind == "answerable") == 4
