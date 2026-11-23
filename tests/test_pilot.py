"""The practice set for the pilot: sound, and sharing no question, fact or answering passage with
the golden set, so the pilot never shows a golden question answered before the golden run."""

from pathlib import Path

from disease_division.golden import check, load_questions
from disease_division.kb import all_passages, load_documents

ROOT = Path(__file__).resolve().parents[1]
PRACTICE = load_questions(ROOT / "evals/pilot.toml")
GOLDEN = load_questions(ROOT / "evals/questions.toml")


def test_the_practice_set_passes_every_golden_set_check():
    assert check(PRACTICE, load_documents(ROOT / "kb")) == []


def test_the_practice_set_has_every_kind_of_question():
    kinds = [q.kind for q in PRACTICE]
    assert (len(PRACTICE), kinds.count("answerable"), kinds.count("staff_only")) == (20, 13, 2)
    assert kinds.count("no_answer") == 5


def test_no_practice_question_shares_a_question_or_a_fact_with_the_golden_set():
    golden_evidence = [q.evidence for q in GOLDEN if q.evidence]
    for q in PRACTICE:
        assert q.question not in {g.question for g in GOLDEN}
        assert not any(q.evidence and (q.evidence in e or e in q.evidence) for e in golden_evidence)
        assert not q.id.startswith("q")


def test_no_practice_answer_lives_in_a_passage_that_answers_a_golden_question():
    passages = all_passages(load_documents(ROOT / "kb"))

    def home(q):
        return {p.id for p in passages if q.evidence and q.evidence in p.text}

    golden_homes = set().union(*(home(q) for q in GOLDEN))
    assert all(not home(q) & golden_homes for q in PRACTICE)
