"""The real stacks and the real golden set, as committed."""

from collections import Counter
from pathlib import Path

import pytest

from disease_division.golden import check, load_questions
from disease_division.kb import CANARY, load_documents

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


def test_every_staff_only_page_carries_exactly_one_canary(documents):
    for document in documents:
        expected = 1 if document.visibility == "staff" else 0
        assert len(CANARY.findall(document.body)) == expected, document.id


def test_no_two_pages_share_a_canary(documents):
    canaries = [c for d in documents for c in CANARY.findall(d.body)]
    assert len(canaries) == len(set(canaries))


def test_some_true_answers_come_from_outside_sources(questions, documents):
    # Defenses that distrust the web and email will cost these answers. Measuring that cost
    # is part of the experiment, so the golden set must include them.
    outside = {d.id for d in documents if d.source != "staff"}
    assert sum(q.doc in outside for q in questions if q.kind == "answerable") == 4
