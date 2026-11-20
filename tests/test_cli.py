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
