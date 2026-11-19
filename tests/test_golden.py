"""The checks that keep the golden set honest, each shown catching its fault."""

import pytest

from disease_division.golden import Question, check, mentions, states
from disease_division.kb import Document

PAGES = [
    Document(
        "fees",
        "Fees",
        "staff",
        "public",
        "A bag costs NGN 8,000.\n\n## Seats\n\nA seat costs NGN 3,000.",
    ),
    Document("secret", "Secret", "staff", "staff", "Agents may give NGN 20,000."),
]


def answerable(**changes):
    fields = dict(
        id="q01",
        kind="answerable",
        question="How much is a bag?",
        doc="fees",
        evidence="A bag costs NGN 8,000.",
        answer=("8,000",),
    )
    fields.update(changes)
    return Question(**fields)


def test_a_sound_question_raises_no_problem():
    assert check([answerable()], PAGES) == []


@pytest.mark.parametrize(
    "text, phrase, found",
    [
        ("costs NGN 8,000", "8,000", True),
        ("aged 17", "7", False),
        ("a 10% bonus", "10%", True),
        ("Open until 22:00.", "22:00", True),
        ("DUTY MANAGER", "duty manager", True),
    ],
)
def test_facts_are_matched_as_whole_words(text, phrase, found):
    assert mentions(text, phrase) is found


def test_any_alternative_states_a_fact():
    assert states("a 10 percent bonus", "10% | 10 percent")
    assert not states("a 12% bonus", "10% | 10 percent")


@pytest.mark.parametrize(
    "question, complaint",
    [
        (answerable(evidence="A bag costs NGN 9,000."), "exactly once, not 0 times"),
        (answerable(doc="nowhere"), "no page has the id"),
        (answerable(doc="secret"), "must point at a public page"),
        (answerable(answer=("9,000",)), "does not state '9,000'"),
        (answerable(answer=()), "lists no facts"),
        (answerable(evidence="NGN 8,000.\n\n## Seats\n\nA seat"), "crosses a section break"),
        (answerable(kind="rumour"), "kind must be one of"),
        (answerable(kind="staff_only"), "must point at a staff page"),
    ],
)
def test_each_fault_in_an_answerable_question_is_named(question, complaint):
    problems = check([question], PAGES)
    assert any(complaint in problem for problem in problems), problems


def test_evidence_that_appears_on_two_pages_is_refused():
    pages = PAGES + [Document("copy", "Copy", "staff", "public", "A bag costs NGN 8,000.")]
    assert any("exactly once, not 2 times" in p for p in check([answerable()], pages))


def test_a_repeated_id_is_refused():
    assert any("used twice" in p for p in check([answerable(), answerable()], PAGES))


def test_a_no_answer_question_must_prove_its_absence():
    sound = Question("q02", "no_answer", "Do you sell insurance?", absent=("insurance",))
    assert check([sound], PAGES) == []

    present = Question("q02", "no_answer", "How much is a seat?", absent=("seat",))
    assert any("'seat' appears in the stacks" in p for p in check([present], PAGES))

    unproven = Question("q02", "no_answer", "Do you sell insurance?")
    assert any("lists the terms" in p for p in check([unproven], PAGES))
