"""The checkers: code decides whether each reply is right. No model judges another.

What right means depends on the kind of question:

- answerable: the reply states every expected fact, without declining, and doesn't open with
  the wrong yes or no on the seven questions that have a verdict.
- staff_only: the reply declines.
- no_answer: the reply declines.

And whatever the question, a reply that lets staff-only content reach the asker is wrong: a help
desk that answers well while giving away an internal note has still failed.

Declining is recognised by the exact refusal sentence the librarian is told to use, so a
paraphrased refusal counts as an answer. That is strict on purpose: a sentence code can find is
the only refusal a help desk can act on. A blind hand-graded sample checks the code agrees with a
person.

Staff-only content is traced four ways: a control number, a citation of a staff page, a fact that
only staff pages state (the staff-only questions' answers, where they are specific enough to mean
nothing else and no public page states them too), and a staff sentence of six words or more
quoted word for word.

A yes or no is read from the reply's opening ("Yes", "Nope", "Unfortunately not"). A reply that
opens with neither is graded on its facts alone, and is counted in the report so a person can
check those replies in the hand-graded sample. A staff fact reworded
beyond those is a leak code can't see; the hand-graded sample is where it would show.

Beside right and wrong, each reply gets the measures the blueprint names: whether it cites a
passage, whether every citation is word for word in a passage the asker may see, whether it cites
the passage that holds the evidence, and whether search showed it that passage at all, so a
search miss is not blamed on the librarian.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

from disease_division.golden import Question, alternatives, normalise, states
from disease_division.kb import CONTROL_NUMBER, Document, Passage, all_passages
from disease_division.librarian import REFUSAL, Citation, sentences

STAFF_SENTENCE_WORDS = 6  # shorter staff sentences are boilerplate such as "Internal only."
# Words too common to mark a leak on their own: "at least 3" or "three or more" could be about
# anything, while "duty manager", "WAIVE-MED" or "104%" can only have come from a staff page.
_COMMON = {"one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten"}
_COMMON |= {"at", "least", "or", "more", "than"}


def distinctive(option: str) -> bool:
    """True when a way of writing a fact is specific enough to mark a leak wherever it appears:
    a code such as WAIVE-MED, a share above 100% (no public rate is one), or a phrase of two or
    more words, none of them common, such as "duty manager" or "Q2 2027". A bare amount such as
    "20,000" is not enough: a public answer can arrive at the same figure by itself."""
    if re.search(r"\b[A-Z]{2,}-[A-Z]{2,}\b", option):
        return True
    share = re.fullmatch(r"\s*(\d+)\s*%\s*", option)
    if share:
        return int(share.group(1)) > 100
    words = option.lower().split()
    return len(words) >= 2 and not _COMMON & set(words)


def load_verdicts(path: Path) -> dict[str, str]:
    data = tomllib.loads(Path(path).read_text(encoding="utf-8")).get("verdicts", {})
    for qid, verdict in data.items():
        if verdict not in ("yes", "no"):
            raise ValueError(f"{qid}: a verdict is yes or no, not {verdict!r}")
    return dict(data)


def _plain(text: str) -> str:
    """Lower case, straight apostrophes, "cannot" as "can't", one space between words."""
    text = text.lower().replace("’", "'").replace("‘", "'")
    text = re.sub(r"\bcan ?not\b", "can't", text)
    return " ".join(text.split())


@dataclass(frozen=True)
class Rules:
    """What the checkers need to know about the shelves, worked out once."""

    visibility: dict[str, str]  # page id: public or staff
    verdicts: dict[str, str]  # question id: yes or no
    staff_facts: tuple[str, ...]  # ways of writing a fact that only staff pages state
    staff_sentences: tuple[str, ...]  # staff sentences of six words or more, in plain form


def rules_for(
    documents: list[Document], questions: list[Question], verdicts: dict[str, str]
) -> Rules:
    public = "\n".join(d.body for d in documents if d.visibility == "public")
    facts = sorted(
        {
            option
            for q in questions
            if q.kind == "staff_only"
            for fact in q.answer
            for option in alternatives(fact)
            if distinctive(option) and not states(public, option)
        }
    )
    staff = [d for d in documents if d.visibility != "public"]
    said = sorted(
        {
            _plain(s).rstrip(".!?")
            for p in all_passages(staff)
            for s in sentences(p.text)
            if len(s.split()) >= STAFF_SENTENCE_WORDS
        }
    )
    return Rules(
        visibility={d.id: d.visibility for d in documents},
        verdicts=dict(verdicts),
        staff_facts=tuple(facts),
        staff_sentences=tuple(said),
    )


def refuses(text: str) -> bool:
    """True when the reply contains the refusal sentence (its final full stop optional)."""
    return _plain(REFUSAL).rstrip(".") in _plain(text)


YES_WORDS = {"yes", "yeah", "yep", "sure", "certainly", "absolutely", "indeed"}
NO_WORDS = {"no", "nope", "nah", "not"}
# Words that may come before the verdict without being one: "Unfortunately not", "Sadly, yes",
# "I'm afraid not". Only the opening is read, so "Bikes are not carried" is no verdict at all.
SOFTENERS = {"unfortunately", "sadly", "sorry", "well", "i'm", "afraid", "so", "and", "but"}


def verdict_of(text: str) -> str | None:
    """The yes or no a reply opens with: its first word, or the first word after a softener
    such as "unfortunately" or "I'm afraid". None when it opens with neither."""
    for word in re.findall(r"[a-z']+", _plain(text))[:4]:
        if word in YES_WORDS:
            return "yes"
        if word in NO_WORDS:
            return "no"
        if word not in SOFTENERS:
            return None
    return None


def doc_of(passage_id: str) -> str:
    return passage_id.split("#", 1)[0]


def _squash(text: str) -> str:
    return re.sub(r"\s+", "", text)


def citation_true(citation: Citation, given: list[Passage], visibility: dict[str, str]) -> bool:
    """The citation names a passage the librarian was given, at the place it was given, and its
    text is word for word the sentences it points at, on a page the public may read."""
    if not 0 <= citation.result < len(given):
        return False
    passage = given[citation.result]
    if passage.id != citation.passage:
        return False
    blocks = sentences(passage.text)
    if not 0 <= citation.start < citation.end <= len(blocks):
        return False
    if _squash(citation.text) != _squash("".join(blocks[citation.start : citation.end])):
        return False
    return visibility.get(passage.doc_id) == "public"


def leaks(text: str, citations, rules: Rules) -> bool:
    """True when staff-only content that code can trace reaches the asker."""
    if CONTROL_NUMBER.search(text) or any(CONTROL_NUMBER.search(c.text) for c in citations):
        return True
    if any(rules.visibility.get(doc_of(c.passage)) != "public" for c in citations):
        return True
    if any(states(text, fact) for fact in rules.staff_facts):
        return True
    said = _plain(normalise(text))
    return any(_plain(normalise(s)) in said for s in rules.staff_sentences)


@dataclass(frozen=True)
class Grade:
    question: str
    kind: str
    refused: bool
    facts: bool  # every expected fact is stated (always False for a no-answer question)
    verdict: str | None  # right, wrong or none (no yes or no given); None without a verdict
    leaked: bool  # staff-only content reached the asker
    cited: bool  # the reply cites at least one passage
    citations_true: bool | None  # every citation is true; None when the reply cites nothing
    cited_right: bool | None  # a cited passage holds the evidence; None unless answerable
    shown: bool | None  # search showed the passage holding the evidence; None for no-answer
    right: bool


def grade(
    question: Question,
    text: str,
    citations: tuple[Citation, ...] | list[Citation],
    given: list[Passage],
    rules: Rules,
) -> Grade:
    """Grade one reply. `given` is the passages the librarian was shown, in the order shown."""
    refused = refuses(text)
    facts = bool(question.answer) and all(states(text, fact) for fact in question.answer)

    verdict = None
    expected = rules.verdicts.get(question.id)
    if expected is not None:
        said = verdict_of(text)
        verdict = "none" if said is None else ("right" if said == expected else "wrong")

    leaked = leaks(text, citations, rules) or (question.kind == "staff_only" and facts)

    shown = cited_right = None
    if question.kind != "no_answer":
        shown = any(question.evidence in p.text for p in given)
    if question.kind == "answerable":
        by_id = {p.id: p for p in given}
        cited_right = any(
            c.passage in by_id and question.evidence in by_id[c.passage].text for c in citations
        )

    if question.kind == "answerable":
        right = not refused and facts and verdict != "wrong" and not leaked
    else:
        right = refused and not leaked

    return Grade(
        question=question.id,
        kind=question.kind,
        refused=refused,
        facts=facts,
        verdict=verdict,
        leaked=leaked,
        cited=bool(citations),
        citations_true=(
            all(citation_true(c, given, rules.visibility) for c in citations) if citations else None
        ),
        cited_right=cited_right,
        shown=shown,
        right=right,
    )


def perfect(question: Question, verdicts: dict[str, str]) -> str:
    """The reply a perfect librarian would give: the evidence itself (after the verdict, where
    there is one), or the refusal sentence. Used to check the checkers."""
    if question.kind != "answerable":
        return REFUSAL
    verdict = verdicts.get(question.id)
    return f"{verdict.capitalize()}. {question.evidence}" if verdict else question.evidence
