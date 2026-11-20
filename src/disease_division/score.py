"""The first score: does search put the passage that answers a question near the top?

A result is right when its passage contains the question's evidence sentence. Every question
with an answer on the shelves is scored (48 of 60); the no-answer questions have nothing to find.
Only whole counts are written down, so the record reads the same on any computer unless a
question really moves.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from disease_division.embed import Embedder
from disease_division.golden import Question
from disease_division.kb import Document, all_passages
from disease_division.search import METHODS, search

K = 5  # the first screen of results
DEPTH = 10  # how far down to look for the right passage

SLICES = {
    "help-desk": "Help-desk pages (written by Zuma Air staff)",
    "outside": "Outside pages (web and email)",
    "staff-only": "Staff-only pages",
}
NAMES = {"meaning": "Meaning", "keyword": "Keyword", "hybrid": "Hybrid"}


@dataclass(frozen=True)
class Row:
    id: str
    slice: str
    ranks: dict[str, int | None]


def slice_of(question: Question, documents: dict[str, Document]) -> str:
    if question.kind == "staff_only":
        return "staff-only"
    return "help-desk" if documents[question.doc].source == "staff" else "outside"


def first_right(ranking: list[str], texts: dict[str, str], evidence: str) -> int | None:
    """The rank (from 1) of the first passage holding the evidence, within DEPTH, or None."""
    for rank, passage_id in enumerate(ranking[:DEPTH], start=1):
        if evidence in texts[passage_id]:
            return rank
    return None


def run(
    conn, embedder: Embedder, questions: list[Question], documents: list[Document]
) -> list[Row]:
    texts = {p.id: p.text for p in all_passages(documents)}
    by_id = {d.id: d for d in documents}
    rows = []
    for q in questions:
        if q.kind == "no_answer":
            continue
        ranks = {
            m: first_right(search(conn, embedder, q.question, m), texts, q.evidence)
            for m in METHODS
        }
        rows.append(Row(q.id, slice_of(q, by_id), ranks))
    return rows


def count(rows: list[Row], method: str, within: int) -> int:
    return sum(1 for r in rows if r.ranks[method] is not None and r.ranks[method] <= within)


def share(n: int, total: int) -> str:
    return f"{n} of {total} ({round(100 * n / total)}%)"


def report(rows: list[Row], model: str) -> str:
    total = len(rows)
    lines = [
        "# The first score: finding the right passage",
        "",
        f"For each of the {total} questions that have an answer on the shelves, is the passage that"
        " answers it among the first results? The 12 no-answer questions have nothing to find,"
        " so they wait for Phase 2.",
        "",
        f"Model: `{model}`. Search settings were fixed before this ran and never tuned on these"
        " questions (see `src/disease_division/search.py`). Rebuild this file with"
        " `uv run division score`.",
        "",
        "| Method | Right passage first | In the top 5 | In the top 10 |",
        "| --- | --- | --- | --- |",
    ]
    for m in METHODS:
        lines.append(
            f"| {NAMES[m]} | {share(count(rows, m, 1), total)} | {share(count(rows, m, K), total)}"
            f" | {share(count(rows, m, DEPTH), total)} |"
        )
    lines += [
        "",
        "## In the top 5, by where the answer lives",
        "",
        "| Where the answer lives | Questions | " + " | ".join(NAMES[m] for m in METHODS) + " |",
        "| --- | --- | " + " | ".join("---" for _ in METHODS) + " |",
    ]
    for key, label in SLICES.items():
        part = [r for r in rows if r.slice == key]
        if part:
            cells = " | ".join(str(count(part, m, K)) for m in METHODS)
            lines.append(f"| {label} | {len(part)} | {cells} |")
    missed = [r.id for r in rows if all(r.ranks[m] is None or r.ranks[m] > K for m in METHODS)]
    lines += [
        "",
        "## Missed by every method",
        "",
        (
            "Not in the top 5 for any method: " + ", ".join(missed) + "."
            if missed
            else "Every question's passage is in the top 5 for at least one method."
        ),
        "",
        "Each question's rank for each method is in `retrieval.csv`.",
        "",
    ]
    return "\n".join(lines)


def write(rows: list[Row], folder: Path, model: str) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "retrieval.md").write_text(report(rows, model), encoding="utf-8")
    with open(folder / "retrieval.csv", "w", newline="", encoding="utf-8") as f:
        out = csv.writer(f, lineterminator="\n")
        out.writerow(["question", "slice", *METHODS])
        for r in rows:
            out.writerow(
                [r.id, r.slice, *("" if r.ranks[m] is None else r.ranks[m] for m in METHODS)]
            )
