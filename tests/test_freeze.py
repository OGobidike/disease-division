"""The freeze: the golden set and the pages it is scored on, fixed before any search ran.

Card D2 set the first two checksums on 2026-11-20, before the first search over the golden set.
From then on the questions are never edited after seeing results, and neither are the pages they
quote. Card D3 added the yes-or-no verdicts on 2026-11-23, before any model answered a golden
question, and froze them the same way.
Card D5 froze, on 2026-11-26, the three results the attack rules are measured against: the
search ranks of the first score, and the golden run's replies and grades. An attack may only aim
at a question that was clean there, so those files must never move under the attacks.
Card D5 then froze the 30 attack pages and their specs on 2026-11-27, after the audit and before
any search had run over them or the librarian had read one.
If one of these tests fails, something changed that the scores depend on: put it back, or start
a new, separately named golden set rather than editing this one.
"""

import hashlib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

QUESTIONS_MD5 = "9e9bcb26c8be9a8e68d164191bbaedb4"
PAGES_MD5 = "0722f2f695f76d6e0b5384d3a96f75e0"
VERDICTS_MD5 = "690f18bfc6a593be0569a501bb4d4adf"
ATTACKS_MD5 = "99b0b3997fce8189688a966858661cbf"
ATTACK_PAGES_MD5 = "bd1ba4987590e2bb83d666d8394494bf"
# What the attacks are measured against (Card D5).
BASELINE_MD5 = {
    "results/retrieval.csv": "cc8205a9b85222ec6b8e5adb4e48910e",
    "results/runs/golden-haiku-5-5.jsonl": "2beb9665a5ad7d527c800b6245e2ea8f",
    "results/answers-haiku-5-5.csv": "a03c748013106dd53bdbd23ec4e75679",
}


def folder_md5(folder: Path) -> str:
    digest = hashlib.md5()
    for page in sorted(folder.glob("*.md")):
        digest.update(page.name.encode() + b"\0" + page.read_bytes() + b"\0")
    return digest.hexdigest()


def test_the_golden_questions_are_frozen():
    assert (
        hashlib.md5((ROOT / "evals" / "questions.toml").read_bytes()).hexdigest() == QUESTIONS_MD5
    )


def test_the_yes_or_no_verdicts_are_frozen():
    assert hashlib.md5((ROOT / "evals" / "verdicts.toml").read_bytes()).hexdigest() == VERDICTS_MD5


def test_the_pages_they_are_scored_on_are_frozen():
    assert folder_md5(ROOT / "kb") == PAGES_MD5


def test_the_freeze_notices_a_one_letter_change(tmp_path):
    for page in sorted((ROOT / "kb").glob("*.md")):
        (tmp_path / page.name).write_bytes(page.read_bytes())
    first = sorted(tmp_path.glob("*.md"))[0]
    first.write_text(first.read_text(encoding="utf-8").replace("Zuma", "Zumo", 1), encoding="utf-8")
    assert folder_md5(tmp_path) != PAGES_MD5


@pytest.mark.parametrize("path", sorted(BASELINE_MD5))
def test_what_the_attacks_are_measured_against_is_frozen(path):
    assert hashlib.md5((ROOT / path).read_bytes()).hexdigest() == BASELINE_MD5[path]


def test_the_attacks_are_frozen():
    assert hashlib.md5((ROOT / "evals" / "attacks.toml").read_bytes()).hexdigest() == ATTACKS_MD5
    assert folder_md5(ROOT / "attacks") == ATTACK_PAGES_MD5
