"""Running the librarian over a question set: the record it keeps, the budget it obeys, how it
resumes, and the report built from the record. The model is a stand-in that costs nothing."""

import json
from pathlib import Path

import pytest

from disease_division.golden import load_questions
from disease_division.grade import load_verdicts
from disease_division.kb import Passage, all_passages, load_documents
from disease_division.librarian import REFUSAL, Citation, Reply, sentences
from disease_division.run import pilot_summary, read_records, report, run, run_path, write_csv

ROOT = Path(__file__).resolve().parents[1]
DOCUMENTS = load_documents(ROOT / "kb")
QUESTIONS = load_questions(ROOT / "evals/questions.toml")
VERDICTS = load_verdicts(ROOT / "evals/verdicts.toml")
PASSAGES = {p.id: p for p in all_passages(DOCUMENTS)}


class EchoModel:
    """Quotes the first sentence of the first passage it is given, citing it, or declines when
    it is given nothing. Each call 'costs' 1,000 tokens in and 100 out on Haiku's prices."""

    name = "claude-haiku-5-5"

    def __init__(self):
        self.calls = []

    def answer(self, question, passages, closed_book=False):
        self.calls.append((question, [p.id for p in passages], closed_book))
        if not passages:
            return Reply(REFUSAL, (), "end_turn", self.name, 1_000, 100)
        first = sentences(passages[0].text)[0]
        return Reply(
            first, (Citation(passages[0].id, 0, 0, 1, first),), "end_turn", self.name, 1_000, 100
        )


def retrieve_answer_page(question):
    """A perfect search: the passage holding each golden question's evidence, else nothing."""
    q = next(q for q in QUESTIONS if q.question == question)
    return [p for p in PASSAGES.values() if q.evidence and q.evidence in p.text][:1]


def test_every_reply_is_recorded_with_what_the_librarian_was_shown(tmp_path):
    path = tmp_path / "golden.jsonl"
    calls, spent, finished = run(QUESTIONS[:3], EchoModel(), retrieve_answer_page, path, 2, 1.0)
    records = read_records(path)
    assert (calls, finished) == (6, True)
    assert spent == pytest.approx(6 * (1_000 * 0.10 + 100 * 0.50) / 1_000_000)
    assert [(r["question"], r["repeat"]) for r in records] == [
        ("q01", 1), ("q02", 1), ("q03", 1), ("q01", 2), ("q02", 2), ("q03", 2),
    ]  # fmt: skip
    first = records[0]
    assert first["passages"] == ["changing-a-flight#2"]
    assert first["citations"][0]["passage"] == "changing-a-flight#2"
    assert first["method"] == "hybrid" and first["effort"] == "medium"
    assert first["closed_book"] is False and first["stop_reason"] == "end_turn"


def test_a_stopped_run_resumes_without_asking_again(tmp_path):
    path = tmp_path / "golden.jsonl"
    run(QUESTIONS[:2], EchoModel(), retrieve_answer_page, path, 1, 1.0)
    model = EchoModel()
    calls, _, finished = run(QUESTIONS[:4], model, retrieve_answer_page, path, 1, 1.0)
    assert (calls, finished) == (2, True)
    assert [c[0] for c in model.calls] == [QUESTIONS[2].question, QUESTIONS[3].question]
    assert len(read_records(path)) == 4


def test_the_budget_stops_the_run_before_the_next_call(tmp_path):
    path = tmp_path / "golden.jsonl"
    per_call = (1_000 * 0.10 + 100 * 0.50) / 1_000_000
    calls, spent, finished = run(
        QUESTIONS, EchoModel(), retrieve_answer_page, path, 1, budget=2.5 * per_call, log=print
    )
    assert (calls, finished) == (3, False)
    assert spent == pytest.approx(3 * per_call)


def test_closed_book_shows_the_model_no_pages(tmp_path):
    model = EchoModel()
    path = tmp_path / "closed.jsonl"
    run(QUESTIONS[:2], model, retrieve_answer_page, path, 1, 1.0, closed_book=True)
    assert [c[1:] for c in model.calls] == [([], True), ([], True)]
    assert all(r["closed_book"] and r["method"] is None for r in read_records(path))


def test_a_file_from_another_kind_of_run_is_never_mixed_in(tmp_path):
    path = tmp_path / "golden.jsonl"
    run(QUESTIONS[:1], EchoModel(), retrieve_answer_page, path, 1, 1.0)
    with pytest.raises(ValueError, match="other settings"):
        run(QUESTIONS[:1], EchoModel(), retrieve_answer_page, path, 1, 1.0, closed_book=True)


def test_a_change_of_settings_starts_a_new_run_instead_of_joining_the_old_one(
    tmp_path, monkeypatch
):
    from disease_division import librarian

    path = tmp_path / "pilot.jsonl"
    run(QUESTIONS[:2], EchoModel(), retrieve_answer_page, path, 1, 1.0)
    monkeypatch.setattr(librarian, "SYSTEM", librarian.SYSTEM + " Be brief.")
    with pytest.raises(ValueError, match="Move the file aside"):
        run(QUESTIONS[:4], EchoModel(), retrieve_answer_page, path, 1, 1.0)
    assert len(read_records(path)) == 2


def test_runs_are_named_by_kind_and_model():
    assert run_path(Path("results/runs"), "golden", "claude-haiku-5-5") == Path(
        "results/runs/golden-haiku-5-5.jsonl"
    )


@pytest.fixture(scope="module")
def golden(tmp_path_factory):
    path = tmp_path_factory.mktemp("runs") / "golden.jsonl"
    run(QUESTIONS, EchoModel(), retrieve_answer_page, path, 2, 1.0, log=lambda _: None)
    return read_records(path)


def test_the_report_counts_what_the_checkers_decide(golden):
    text = report(golden, [], QUESTIONS, DOCUMENTS, VERDICTS)
    # The stand-in quotes the first sentence of the answering passage. That is right where the
    # evidence is that sentence and there is no verdict to give, and every staff-only question
    # leaks, because it quotes the staff page.
    assert "`claude-haiku-5-5` at effort medium" in text
    assert "60 questions, 2 times each: 120 replies" in text
    assert "| Staff only | 8 | declines | 0 of 16 (0%) | 0 of 8 |" in text
    assert "a reply that lets staff-only content reach the asker is wrong" in text
    assert "Unfinished" not in text
    assert "| No answer | 12 | declines | 24 of 24 (100%) | 12 of 12 |" in text
    assert "(the evidence itself, or the refusal sentence) is graded right 60 times" in text
    assert "an empty reply 0 times, and declining everything 20 times" in text
    assert "q41 | staff only | 0 of 2 | answered without declining and leaked (2)" in text


def test_the_report_is_the_same_every_time_from_the_same_records(golden):
    assert report(golden, [], QUESTIONS, DOCUMENTS, VERDICTS) == report(
        golden, [], QUESTIONS, DOCUMENTS, VERDICTS
    )


def test_the_report_adds_the_closed_book_run_when_there_is_one(golden, tmp_path):
    path = tmp_path / "closed.jsonl"
    answerable = [q for q in QUESTIONS if q.kind == "answerable"]
    run(answerable, EchoModel(), retrieve_answer_page, path, 1, 1.0, closed_book=True)
    text = report(golden, read_records(path), QUESTIONS, DOCUMENTS, VERDICTS)
    assert "## Closed book: no pages at all" in text
    assert "Replies stating every expected fact: 0 of 40 (0%)." in text
    assert "Questions answered that way every time: none." in text
    assert "The 40 answerable questions, once each" in text


def test_the_csv_holds_one_row_per_question(golden, tmp_path):
    out = tmp_path / "answers.csv"
    write_csv(out, golden, QUESTIONS, DOCUMENTS, VERDICTS)
    rows = out.read_text(encoding="utf-8").splitlines()
    assert rows[0] == (
        "question,slice,replies,right,refused,facts,leaked,cited,citations_true,cited_right,"
        "shown,verdict_right"
    )
    assert len(rows) == 61
    assert rows[1] == "q01,help-desk,2,2,0,2,0,2,2,2,2,"  # no verdict on q01: left blank
    assert rows[49].startswith("q49,no-answer,2,") and rows[49].endswith(",,,,")


def test_the_pilot_summary_flags_replies_that_declined_the_wrong_way(tmp_path):
    practice = load_questions(ROOT / "evals/pilot.toml")
    path = tmp_path / "pilot.jsonl"
    run(practice, EchoModel(), lambda q: [], path, 1, 1.0, log=lambda _: None)
    text = pilot_summary(read_records(path), practice)
    assert text.count("CHECK") == 13 + 1  # 13 answerable questions declined, plus the footnote
    assert "golden run (60 questions, 3 times) costs about $0.03" in text
    assert "(2,520 calls) about $0.38 on claude-haiku-5-5" in text


def test_the_runner_writes_plain_json_lines(tmp_path):
    path = tmp_path / "golden.jsonl"
    run(QUESTIONS[:1], EchoModel(), retrieve_answer_page, path, 1, 1.0)
    (line,) = path.read_text(encoding="utf-8").splitlines()
    assert json.loads(line)["question"] == "q01"


def test_search_feeds_the_librarian_its_passages(db, fake_embedder):
    from disease_division import store
    from disease_division.cli import retriever
    from disease_division.librarian import PASSAGES as N

    store.load(db, DOCUMENTS, fake_embedder)
    retrieve = retriever(db, fake_embedder, DOCUMENTS)
    passages = retrieve("How much does it cost to change a Savanna fare?")
    assert len(passages) == N and all(isinstance(p, Passage) for p in passages)
    assert len({p.id for p in passages}) == N


def test_an_unfinished_run_is_reported_as_unfinished(golden):
    text = report(golden[:100], [], QUESTIONS, DOCUMENTS, VERDICTS)
    assert "**Unfinished: 100 of 120 replies are in.**" in text
    # q41 to q60 have one reply of two, so none of them can be right every time yet.
    assert "| No answer | 12 | declines | 12 of 12 (100%) | 0 of 12 |" in text


def test_a_run_that_mixes_settings_is_refused(golden):
    mixed = [dict(golden[0], settings="something-else"), *golden[1:]]
    with pytest.raises(ValueError, match="mixes replies made under different settings"):
        report(mixed, [], QUESTIONS, DOCUMENTS, VERDICTS)


def test_citation_truth_counts_only_the_replies_that_cite(tmp_path):
    class Quiet(EchoModel):
        def answer(self, question, passages, closed_book=False):
            reply = super().answer(question, passages, closed_book)
            return Reply(reply.text, (), "end_turn", self.name, 1_000, 100)

    path = tmp_path / "golden.jsonl"
    run(QUESTIONS, Quiet(), retrieve_answer_page, path, 1, 1.0, log=lambda _: None)
    text = report(read_records(path), [], QUESTIONS, DOCUMENTS, VERDICTS)
    assert (
        "| Every citation is word for word in a public page, of the replies that cite | - |" in text
    )


def test_an_unfinished_run_counts_against_the_repeats_it_was_asked_for(tmp_path):
    path = tmp_path / "golden.jsonl"
    per_call = (1_000 * 0.10 + 100 * 0.50) / 1_000_000
    run(QUESTIONS, EchoModel(), retrieve_answer_page, path, 3, 69.5 * per_call, log=lambda _: None)
    text = report(read_records(path), [], QUESTIONS, DOCUMENTS, VERDICTS)
    assert "60 questions, 3 times each: 70 replies" in text
    assert "**Unfinished: 70 of 180 replies are in.**" in text
