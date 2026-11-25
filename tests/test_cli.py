"""The `division shelf` command."""

from pathlib import Path

import pytest

from disease_division.cli import main

ROOT = Path(__file__).resolve().parents[1]


def test_shelf_reports_the_real_stacks_and_passes(capsys):
    code = main(
        ["shelf", "--kb", str(ROOT / "kb"), "--questions", str(ROOT / "evals/questions.toml")]
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "The stacks: 59 pages" in out
    assert "40 answerable · 8 staff only · 12 no answer" in out
    assert "Every check passed." in out


def test_shelf_names_each_problem_and_fails(tmp_path, capsys):
    kb = tmp_path / "kb"
    kb.mkdir()
    (kb / "leaky.md").write_text(
        '+++\nid = "leaky"\ntitle = "Leaky"\nsource = "web"\nvisibility = "public"\n+++\n\n'
        "Note ZA-DC-0001 here.\n",
        encoding="utf-8",
    )
    questions = tmp_path / "questions.toml"
    questions.write_text(
        '[[question]]\nid = "q01"\nkind = "no_answer"\n'
        'question = "Any notes?"\nabsent = ["note"]\n',
        encoding="utf-8",
    )
    code = main(["shelf", "--kb", str(kb), "--questions", str(questions)])
    out = capsys.readouterr().out
    assert code == 1
    assert "leaky: a public page carries no control number" in out
    assert "q01: 'note' appears in the stacks" in out


def test_shelf_says_plainly_when_it_cannot_read(tmp_path, capsys):
    code = main(["shelf", "--kb", str(tmp_path), "--questions", str(tmp_path / "none.toml")])
    assert code == 1
    assert "Could not read the stacks" in capsys.readouterr().out


def test_shelf_catches_a_staff_section_without_its_control_number(tmp_path, capsys):
    kb = tmp_path / "kb"
    kb.mkdir()
    (kb / "guide.md").write_text(
        '+++\nid = "guide"\ntitle = "Guide"\nsource = "staff"\nvisibility = "staff"\n+++\n\n'
        "Internal.\n\nControl no. ZA-DC-0002\n\n## Limits\n\nUp to NGN 20,000.\n",
        encoding="utf-8",
    )
    questions = tmp_path / "questions.toml"
    questions.write_text(
        '[[question]]\nid = "q01"\nkind = "no_answer"\nquestion = "Any perks?"\n'
        'absent = ["perk"]\n',
        encoding="utf-8",
    )
    assert main(["shelf", "--kb", str(kb), "--questions", str(questions)]) == 1
    assert "guide#2: every section of a staff-only page ends with ZA-DC-0002" in (
        capsys.readouterr().out
    )


def test_store_commands_say_plainly_when_the_database_is_down(monkeypatch, capsys):
    monkeypatch.setenv("DIVISION_DB_URL", "postgresql://division:division@127.0.0.1:1/division")
    assert main(["score", "--kb", str(ROOT / "kb")]) == 1
    assert "Could not reach the store" in capsys.readouterr().out


def test_score_refuses_a_store_that_does_not_match_the_pages(
    db, fake_embedder, monkeypatch, capsys
):
    from disease_division import store
    from disease_division.cli import _store_matches
    from disease_division.kb import load_documents

    documents = load_documents(ROOT / "kb")
    store.load(db, documents[:3], fake_embedder)
    assert not _store_matches(db, documents, fake_embedder.model)
    store.load(db, documents, fake_embedder)
    assert _store_matches(db, documents, fake_embedder.model)
    assert not _store_matches(db, documents, "another-model")
    assert "Run: uv run division load" in capsys.readouterr().out


SHELF = ["shelf", "--kb", str(ROOT / "kb"), "--questions", str(ROOT / "evals/questions.toml")]
SHELF += ["--pilot", str(ROOT / "evals/pilot.toml")]


def test_shelf_also_checks_the_practice_set_and_the_verdicts(capsys):
    assert main([*SHELF, "--verdicts", str(ROOT / "evals/verdicts.toml")]) == 0
    assert "The practice set (for the pilot): 20 questions; yes-or-no verdicts: 7" in (
        capsys.readouterr().out
    )


def test_shelf_catches_a_verdict_on_a_question_that_cannot_have_one(tmp_path, capsys):
    verdicts = tmp_path / "verdicts.toml"
    verdicts.write_text('[verdicts]\nq49 = "no"\n', encoding="utf-8")
    assert main([*SHELF, "--verdicts", str(verdicts)]) == 1
    assert "q49: a verdict needs an answerable golden question" in capsys.readouterr().out


@pytest.mark.parametrize("command", [["ask", "Is there Wi-Fi?"], ["pilot"], ["answer"], ["serve"]])
def test_every_paid_command_stops_first_when_there_is_no_key(
    command, tmp_path, monkeypatch, capsys
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("DIVISION_DB_URL", "postgresql://division:division@127.0.0.1:1/division")
    assert main([*command, "--kb", str(ROOT / "kb")]) == 1
    out = capsys.readouterr().out
    assert out.startswith("No ANTHROPIC_API_KEY.")
    assert "Could not reach the store" not in out


def test_the_key_is_read_from_dot_env_without_overriding_what_is_set(tmp_path, monkeypatch):
    from disease_division.cli import load_env

    env = tmp_path / ".env"
    env.write_text(
        "# a comment\nANTHROPIC_API_KEY='sk-test'\nexport DIVISION_X=1\nDIVISION_Y=from-file\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("DIVISION_X", raising=False)
    monkeypatch.setenv("DIVISION_Y", "already-set")
    load_env(env)
    import os

    assert os.environ["ANTHROPIC_API_KEY"] == "sk-test"
    assert os.environ["DIVISION_X"] == "1"
    assert os.environ["DIVISION_Y"] == "already-set"


def test_the_report_says_plainly_when_there_is_no_run_yet(tmp_path, capsys):
    assert main(["report", "--kb", str(ROOT / "kb"), "--runs", str(tmp_path)]) == 1
    assert "No golden run for claude-haiku-5-5 yet" in capsys.readouterr().out


def test_an_api_error_is_explained_in_one_line(capsys):
    import anthropic
    import httpx2

    from disease_division.cli import call_failed

    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    response = httpx2.Response(429, request=request)
    assert call_failed(anthropic.RateLimitError("slow down", response=response, body=None)) == 1
    assert "Run the same command again: it picks up where it stopped." in capsys.readouterr().out


def test_the_report_explains_a_run_that_mixes_settings_instead_of_crashing(tmp_path, capsys):
    import json

    line = {"question": "q01", "repeat": 1, "repeats": 1, "model": "claude-haiku-5-5"}
    line |= {"settings": "a", "effort": "medium", "method": "hybrid", "passages": []}
    line |= {"text": "", "citations": [], "stop_reason": "end_turn", "input_tokens": 1}
    line |= {"output_tokens": 1, "cache_write_tokens": 0, "cache_read_tokens": 0, "cost": 0.0}
    line |= {"request_id": "", "at": "2026-11-23T00:00:00+00:00"}
    other = dict(line, question="q02", settings="b")
    runs = tmp_path / "runs"
    runs.mkdir()
    (runs / "golden-haiku-5-5.jsonl").write_text(
        json.dumps(line) + "\n" + json.dumps(other) + "\n", encoding="utf-8"
    )
    assert main(["report", "--kb", str(ROOT / "kb"), "--runs", str(runs)]) == 1
    assert "Can't report: the golden run mixes replies" in capsys.readouterr().out


def test_the_sheet_waits_for_a_finished_run_and_never_overwrites(tmp_path, capsys):
    import json

    runs, out = tmp_path / "runs", tmp_path / "results"
    runs.mkdir()
    line = {"question": "q01", "repeat": 1, "repeats": 1, "text": "x", "citations": []}
    (runs / "golden-haiku-5-5.jsonl").write_text(json.dumps(line) + "\n", encoding="utf-8")
    args = ["sheet", "--runs", str(runs), "--out", str(out)]
    assert main(args) == 1
    assert "The golden run has 1 of 60 replies, so no sheet was written" in capsys.readouterr().out
    lines = [dict(line, question=f"q{i:02d}") for i in range(1, 61)]
    (runs / "golden-haiku-5-5.jsonl").write_text(
        "".join(json.dumps(x) + "\n" for x in lines), encoding="utf-8"
    )
    assert main(args) == 0
    assert (out / "hand-grades-haiku-5-5.toml").exists()
    assert main(args) == 1
    assert "already there, so it was left as it is" in capsys.readouterr().out


@pytest.mark.parametrize(
    "budget, args, says",
    [
        ("abc", [], "DIVISION_API_BUDGET must be a number"),
        ("1.00", ["--budget", "0.001"], "can't cover one call at its worst case"),
        ("nan", [], "must be a positive number"),
        ("1.00", ["--budget", "inf"], "must be a positive number"),
        ("1.00", ["--budget", "-1"], "must be a positive number"),
    ],
)
def test_the_server_refuses_a_budget_it_cannot_use(budget, args, says, monkeypatch, capsys):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-not-a-key")
    monkeypatch.setenv("DIVISION_API_BUDGET", budget)
    assert main(["serve", *args, "--kb", str(ROOT / "kb")]) == 1
    assert says in capsys.readouterr().out
