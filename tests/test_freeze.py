"""The freeze: the golden set and the pages it is scored on, fixed before any search ran.

Card D2 set these checksums on 2026-11-20, before the first search over the golden set. From then
on the questions are never edited after seeing results, and neither are the pages they quote.
If one of these tests fails, something changed that the scores depend on: put it back, or start
a new, separately named golden set rather than editing this one.
"""

import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

QUESTIONS_MD5 = "9e9bcb26c8be9a8e68d164191bbaedb4"
PAGES_MD5 = "0722f2f695f76d6e0b5384d3a96f75e0"


def folder_md5(folder: Path) -> str:
    digest = hashlib.md5()
    for page in sorted(folder.glob("*.md")):
        digest.update(page.name.encode() + b"\0" + page.read_bytes() + b"\0")
    return digest.hexdigest()


def test_the_golden_questions_are_frozen():
    assert (
        hashlib.md5((ROOT / "evals" / "questions.toml").read_bytes()).hexdigest() == QUESTIONS_MD5
    )


def test_the_pages_they_are_scored_on_are_frozen():
    assert folder_md5(ROOT / "kb") == PAGES_MD5


def test_the_freeze_notices_a_one_letter_change(tmp_path):
    for page in sorted((ROOT / "kb").glob("*.md")):
        (tmp_path / page.name).write_bytes(page.read_bytes())
    first = sorted(tmp_path.glob("*.md"))[0]
    first.write_text(first.read_text(encoding="utf-8").replace("Zuma", "Zumo", 1), encoding="utf-8")
    assert folder_md5(tmp_path) != PAGES_MD5
