"""The golden set: the questions every later phase is scored on, and the checks that keep it honest.

Each question in evals/questions.toml is one of three kinds:

- `answerable`: a member of the public asks, and a public page holds the answer.
- `staff_only`: the answer sits only on a staff-only page, so a public asker should not get it.
- `no_answer`: nothing in the stacks answers it, so the right reply is to say so.

An answerable or staff-only question names its page, quotes the `evidence` (the exact words on
that page that answer it) and lists the `answer` facts a correct reply must contain. A fact may
offer alternatives separated by " | ", such as "two | 2".

Before matching, both texts are normalised (see `normalise`), so a reply may write an amount
the way people really do: "N9,000", "NGN9000", "9000", "20 per cent", "7kg" or "10pm".
Written-out forms ("two", "an hour") are listed as alternatives instead.

A no-answer question lists `absent` terms instead: words that must not appear anywhere in the
stacks, which is how code proves the stacks really don't cover it.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from disease_division.kb import Document, split_passages

KINDS = ("answerable", "staff_only", "no_answer")


@dataclass(frozen=True)
class Question:
    id: str
    kind: str
    question: str
    doc: str = ""
    evidence: str = ""
    answer: tuple[str, ...] = field(default_factory=tuple)
    absent: tuple[str, ...] = field(default_factory=tuple)


def load_questions(path: Path) -> list[Question]:
    data = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    questions = []
    for row in data.get("question", []):
        unknown = row.keys() - {"id", "kind", "question", "doc", "evidence", "answer", "absent"}
        if unknown:
            raise ValueError(f"{row.get('id', '?')}: unexpected keys {sorted(unknown)}")
        questions.append(
            Question(
                id=row["id"],
                kind=row["kind"],
                question=row["question"],
                doc=row.get("doc", ""),
                evidence=row.get("evidence", ""),
                answer=tuple(row.get("answer", ())),
                absent=tuple(row.get("absent", ())),
            )
        )
    return questions


def alternatives(fact: str) -> list[str]:
    return [option.strip() for option in fact.split("|") if option.strip()]


_REWRITES = [
    # Dashes of every width read as a hyphen: "21–24" is "21-24".
    (re.compile("[\u2012\u2013\u2014\u2015\u2212]"), "-"),
    # Naira prefixes go: "NGN 9,000", "NGN9,000", the naira sign and "N9,000" all become "9,000".
    (re.compile(r"(?<!\w)(?:ngn|\u20a6)\s*(?=\d)", re.IGNORECASE), ""),
    (re.compile(r"(?<!\w)N(?=\d)"), ""),
    # Thousands separators go: "9,000" becomes "9000".
    (re.compile(r"(?<=\d),(?=\d{3}(?!\d))"), ""),
    # "20 per cent", "20 percent" and "20 %" all become "20%".
    (re.compile(r"(\d)\s*(?:%|per\s?cent\b)", re.IGNORECASE), r"\1%"),
    # Units close up the same way every time: "7kg", "7 kilos" and "7 kilograms" become "7 kg".
    (re.compile(r"(\d)\s*(?:kg|kgs|kilos?|kilograms?)\b", re.IGNORECASE), r"\1 kg"),
    (re.compile(r"(\d)\s*(?:wh|watt[- ]?hours?)\b", re.IGNORECASE), r"\1 wh"),
    (re.compile(r"(\d)\s*mins?\b", re.IGNORECASE), r"\1 minutes"),
    # Clock times: "10pm" and "10 p.m." become "10 pm".
    (re.compile(r"(\d)\s*([ap])\.?m\.?(?!\w)", re.IGNORECASE), r"\1 \2m"),
    (re.compile(r"\s+"), " "),
]


def normalise(text: str) -> str:
    """Write amounts, units and times one way, so equal facts compare equal."""
    for pattern, replacement in _REWRITES:
        text = pattern.sub(replacement, text)
    return text.strip()


def mentions(text: str, phrase: str) -> bool:
    """True when the phrase appears as whole words, ignoring case: "7" is not found in "17"."""
    pattern = r"(?<!\w)" + re.escape(normalise(phrase)) + r"(?!\w)"
    return re.search(pattern, normalise(text), flags=re.IGNORECASE) is not None


def states(text: str, fact: str) -> bool:
    """True when the text states the fact in any of its alternative forms."""
    return any(mentions(text, option) for option in alternatives(fact))


def check(questions: list[Question], documents: list[Document]) -> list[str]:
    """Every problem with the golden set, in plain words. An empty list means it is sound."""
    problems = []
    by_id = {document.id: document for document in documents}
    everything = "\n".join(document.body for document in documents)
    lowered = everything.lower()

    seen = set()
    for q in questions:
        if q.id in seen:
            problems.append(f"{q.id}: the id is used twice")
        seen.add(q.id)

        if q.kind not in KINDS:
            problems.append(f"{q.id}: kind must be one of {KINDS}, not {q.kind!r}")
            continue
        if not q.question.strip():
            problems.append(f"{q.id}: the question is empty")

        if q.kind == "no_answer":
            if q.doc or q.evidence or q.answer:
                problems.append(f"{q.id}: a no-answer question names no page, evidence or answer")
            if not q.absent:
                problems.append(f"{q.id}: a no-answer question lists the terms that prove it")
            for term in q.absent:
                if term.lower() in lowered:
                    problems.append(f"{q.id}: {term!r} appears in the stacks")
            continue

        if q.absent:
            problems.append(f"{q.id}: only no-answer questions list absent terms")
        document = by_id.get(q.doc)
        if document is None:
            problems.append(f"{q.id}: no page has the id {q.doc!r}")
            continue
        wanted = "public" if q.kind == "answerable" else "staff"
        if document.visibility != wanted:
            problems.append(f"{q.id}: a {q.kind} question must point at a {wanted} page")
        if not q.evidence:
            problems.append(f"{q.id}: the evidence is empty")
            continue
        count = everything.count(q.evidence)
        if count != 1:
            problems.append(f"{q.id}: the evidence must appear exactly once, not {count} times")
        elif q.evidence not in document.body:
            problems.append(f"{q.id}: the evidence is on another page, not {q.doc!r}")
        elif not any(q.evidence in p.text for p in split_passages(document)):
            problems.append(f"{q.id}: the evidence crosses a section break")
        if not q.answer:
            problems.append(f"{q.id}: the answer lists no facts")
        for fact in q.answer:
            if not states(q.evidence, fact):
                problems.append(f"{q.id}: the evidence does not state {fact!r}")
    return problems
