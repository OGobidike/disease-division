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


from disease_division.run import (  # noqa: E402
    SAMPLE,
    SEED,
    hand_sample,
    kappa,
    lower_bound,
    read_marks,
    sheet,
)


def test_cohens_kappa_rewards_agreement_beyond_chance():
    same = [(True, True)] * 18 + [(False, False)] * 2
    assert kappa(same) == pytest.approx(1.0)
    assert kappa([(True, True)] * 20) is None  # every mark the same: kappa is undefined
    assert kappa([(True, False), (False, True)] * 5) == pytest.approx(-1.0)


def test_the_lower_bound_is_the_exact_95_percent_one():
    from math import comb

    assert lower_bound(20, 20) == pytest.approx(0.025 ** (1 / 20), abs=1e-6)
    assert lower_bound(0, 20) == 0.0
    p = lower_bound(15, 20)
    assert sum(comb(20, i) * p**i * (1 - p) ** (20 - i) for i in range(15, 21)) == pytest.approx(
        0.025, abs=1e-6
    )


def test_the_hand_sample_is_fixed_by_its_seed(golden):
    import random

    assert hand_sample(golden) == random.Random(SEED).sample(golden, SAMPLE)
    assert hand_sample(golden) == hand_sample(list(golden))


def test_the_sheet_shows_each_sampled_reply_and_nothing_the_code_decided(golden, tmp_path):
    path = tmp_path / "sheet.toml"
    path.write_text(sheet(golden, QUESTIONS, VERDICTS), encoding="utf-8")
    import tomllib

    rows = tomllib.loads(path.read_text(encoding="utf-8"))["reply"]
    drawn = [(r["question"], r["repeat"]) for r in hand_sample(golden)]
    assert [(r["question"], r["repeat"]) for r in rows] == drawn
    assert all(r["mark"] == "" and r["why"] == "" for r in rows)
    assert not {"right", "leaked", "facts"} & set().union(*rows)
    assert "R (right) or W (wrong)" in path.read_text(encoding="utf-8")


def marked_sheet(golden, tmp_path, flip=()):
    """The sheet, graded the way the code graded it, with the replies in `flip` marked the
    other way."""
    from disease_division.grade import rules_for
    from disease_division.run import grade_records

    grades = grade_records(golden, QUESTIONS, DOCUMENTS, rules_for(DOCUMENTS, QUESTIONS, VERDICTS))
    right = {(r["question"], r["repeat"]): g.right for r, g in zip(golden, grades)}
    text = sheet(golden, QUESTIONS, VERDICTS)
    rows = text.split("[[reply]]")
    out = [rows[0]]
    for n, row in enumerate(rows[1:], 1):
        r = hand_sample(golden)[n - 1]
        mark = "R" if right[(r["question"], r["repeat"])] != (n in flip) else "W"
        out.append(row.replace('mark = ""', f'mark = "{mark}"').replace('why = ""', 'why = "x"'))
    path = tmp_path / "hand-grades-haiku-5-5.toml"
    path.write_text("[[reply]]".join(out), encoding="utf-8")
    return read_marks(path)


def test_the_report_sets_the_blind_sample_against_the_code(golden, tmp_path):
    text = report(golden, [], QUESTIONS, DOCUMENTS, VERDICTS, marked_sheet(golden, tmp_path))
    assert "## Checked by a person" in text
    assert "They agreed with the code on **20 of 20**" in text
    assert "the true agreement is likely at least 83%" in text
    assert "not the seeded sample" not in text


def test_a_disagreement_is_listed_with_the_persons_reason(golden, tmp_path):
    text = report(golden, [], QUESTIONS, DOCUMENTS, VERDICTS, marked_sheet(golden, tmp_path, {3}))
    assert "on **19 of 20**" in text
    assert "| Reply | The person | The code | Why |" in text


def test_a_sheet_that_is_not_the_seeded_sample_is_called_out(golden, tmp_path):
    hand = marked_sheet(golden, tmp_path)
    hand[0], hand[1] = hand[1], hand[0]
    text = report(golden, [], QUESTIONS, DOCUMENTS, VERDICTS, hand)
    assert "is not the seeded sample of this run" in text


def test_the_rechecks_raise_the_score_by_what_a_person_found_right(golden, tmp_path):
    from disease_division.grade import rules_for
    from disease_division.run import grade_records

    grades = grade_records(golden, QUESTIONS, DOCUMENTS, rules_for(DOCUMENTS, QUESTIONS, VERDICTS))
    from disease_division.run import disputable

    due = [(r["question"], r["repeat"]) for r, g in zip(golden, grades) if disputable(g)]
    rows = [{"question": q, "repeat": n, "mark": "W", "why": "wrong"} for q, n in due]
    rows[0]["mark"] = "R"
    hand = marked_sheet(golden, tmp_path)
    total = sum(g.right for g in grades)
    text = report(golden, [], QUESTIONS, DOCUMENTS, VERDICTS, hand, rows)
    assert f"They marked 1 of them right: {due[0][0]} repeat {due[0][1]}" in text
    assert f"the score is **{total + 1} of 120**" in text
    assert "don't cover exactly" not in text
    assert "don't cover exactly" in report(
        golden, [], QUESTIONS, DOCUMENTS, VERDICTS, hand, rows[1:]
    )


def test_a_mark_that_is_neither_r_nor_w_is_refused(tmp_path):
    path = tmp_path / "marks.toml"
    path.write_text('[[reply]]\nquestion = "q01"\nrepeat = 1\nmark = "maybe"\n', encoding="utf-8")
    with pytest.raises(ValueError, match="has no R or W"):
        read_marks(path)


def test_a_sheet_naming_a_reply_the_run_lacks_is_called_out_not_a_crash(golden, tmp_path):
    hand = marked_sheet(golden, tmp_path)
    hand[0] = dict(hand[0], repeat=9)
    text = report(golden, [], QUESTIONS, DOCUMENTS, VERDICTS, hand)
    assert "is not the seeded sample of this run" in text
    assert "**Hand grades from another sample.**" in text and "of 19**" in text
    assert "drawn at random by a fixed seed" not in text


def test_a_reworded_refusal_on_a_no_answer_question_is_due_a_persons_read():
    from disease_division.grade import grade, rules_for
    from disease_division.run import disputable

    rules = rules_for(DOCUMENTS, QUESTIONS, VERDICTS)
    q49 = next(q for q in QUESTIONS if q.id == "q49")
    q36 = next(q for q in QUESTIONS if q.id == "q36")
    reworded = grade(
        q49, "Sorry, our help pages don't say anything about insurance.", (), [], rules
    )
    assert not reworded.right and disputable(reworded)
    search_miss = grade(q36, REFUSAL, (), [], rules)  # shown nothing: a search miss
    assert not search_miss.right and not disputable(search_miss)


def test_the_sheet_stays_valid_toml_whatever_a_reply_holds(tmp_path):
    import tomllib

    from disease_division.run import toml_string

    awkward = 'a "quote", a back\\slash, a tab\t, DEL\x7f, a bell\x07 and \u20a6 9,000'
    assert tomllib.loads(f"x = {toml_string(awkward)}")["x"] == awkward


def test_a_sheet_with_nothing_from_this_run_is_called_out_not_a_crash(golden, tmp_path):
    hand = [dict(row, repeat=9) for row in marked_sheet(golden, tmp_path)]
    text = report(golden, [], QUESTIONS, DOCUMENTS, VERDICTS, hand)
    assert "0 of its replies are in this run" in text
    assert "agreed with the code" not in text
    assert kappa([]) is None
