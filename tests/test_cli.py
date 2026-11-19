"""The `division shelf` command."""

from pathlib import Path

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
        "Note ZA-CANARY-0001 here.\n",
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
    assert "leaky: a public page carries no canary" in out
    assert "q01: 'note' appears in the stacks" in out


def test_shelf_says_plainly_when_it_cannot_read(tmp_path, capsys):
    code = main(["shelf", "--kb", str(tmp_path), "--questions", str(tmp_path / "none.toml")])
    assert code == 1
    assert "Could not read the stacks" in capsys.readouterr().out
