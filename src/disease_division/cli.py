"""The `division` command."""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

from disease_division.golden import KINDS, check, load_questions
from disease_division.kb import CANARY, all_passages, load_documents


def shelf(kb: Path, questions_path: Path) -> int:
    """Report what is on the shelves and check every rule. Returns the exit code."""
    try:
        documents = load_documents(kb)
        questions = load_questions(questions_path)
    except (OSError, ValueError, KeyError) as error:
        print(f"Could not read the stacks: {error}")
        return 1

    passages = all_passages(documents)
    words = sum(len(d.body.split()) for d in documents)
    sources = Counter(d.source for d in documents)
    visibility = Counter(d.visibility for d in documents)
    kinds = Counter(q.kind for q in questions)

    print(f"The stacks: {len(documents)} pages, {len(passages)} passages, {words:,} words")
    print("  by source:     " + " · ".join(f"{k} {sources[k]}" for k in sorted(sources)))
    print("  by visibility: " + " · ".join(f"{k} {visibility[k]}" for k in sorted(visibility)))
    print(
        f"The golden set: {len(questions)} questions ("
        + " · ".join(f"{kinds[k]} {k.replace('_', ' ')}" for k in KINDS)
        + ")"
    )

    problems = check(questions, documents)
    for document in documents:
        canaries = CANARY.findall(document.body)
        if document.visibility == "staff" and len(canaries) != 1:
            problems.append(f"{document.id}: a staff-only page carries exactly one canary")
        if document.visibility == "public" and canaries:
            problems.append(f"{document.id}: a public page carries no canary")

    if problems:
        print(f"\n{len(problems)} problem(s):")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print("\nEvery check passed.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="division", description="The Disease Division")
    commands = parser.add_subparsers(dest="command", required=True)
    shelf_parser = commands.add_parser("shelf", help="report on the stacks and check every rule")
    shelf_parser.add_argument("--kb", type=Path, default=Path("kb"))
    shelf_parser.add_argument("--questions", type=Path, default=Path("evals/questions.toml"))
    args = parser.parse_args(argv)
    return shelf(args.kb, args.questions)


if __name__ == "__main__":
    sys.exit(main())
