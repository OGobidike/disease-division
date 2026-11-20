"""The `division` command."""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

from disease_division.golden import KINDS, check, load_questions
from disease_division.kb import CONTROL_NUMBER, all_passages, load_documents, split_passages
from disease_division.search import METHODS


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
    owners: dict[str, str] = {}
    for document in documents:
        numbers = set(CONTROL_NUMBER.findall(document.body))
        if document.visibility == "public":
            if numbers:
                problems.append(f"{document.id}: a public page carries no control number")
            continue
        if len(numbers) != 1:
            problems.append(f"{document.id}: a staff-only page carries exactly one control number")
            continue
        number = numbers.pop()
        if number in owners:
            problems.append(f"{document.id}: shares its control number with {owners[number]}")
        owners[number] = document.id
        for passage in split_passages(document):
            if number not in passage.text:
                problems.append(
                    f"{passage.id}: every section of a staff-only page ends with {number}"
                )

    if problems:
        print(f"\n{len(problems)} problem(s):")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print("\nEvery check passed.")
    return 0


def _open_store():
    """Connect to the store, or explain in one line why not."""
    import psycopg

    from disease_division import store

    try:
        return store.connect(connect_timeout=5)
    except psycopg.OperationalError:
        print(
            f"Could not reach the store at {store.url()}. "
            "Is Docker Desktop open, and is the database up (docker compose up -d --wait db)?"
        )
        return None


def load(kb: Path) -> int:
    """Embed every passage and store it, replacing what was there."""
    import time

    from disease_division import store
    from disease_division.embed import FastEmbedder

    documents = load_documents(kb)
    conn = _open_store()
    if conn is None:
        return 1
    embedder = FastEmbedder()
    print(
        f"Embedding the passages with {embedder.model} (the first run downloads it, about 65 MB)..."
    )
    started = time.perf_counter()
    with conn:
        n = store.load(conn, documents, embedder)
    print(
        f"Stored {n} passages from {len(documents)} pages in {time.perf_counter() - started:.1f} s."
    )
    return 0


def _store_matches(conn, documents, model: str) -> bool:
    from disease_division import store

    held = store.stored(conn)
    wanted = {p.id: p.text for p in all_passages(documents)}
    if {k: v[0] for k, v in held.items()} != wanted or any(v[1] != model for v in held.values()):
        print("The store doesn't match the pages on disk. Run: uv run division load")
        return False
    return True


def find(question: str, method: str, kb: Path, top: int) -> int:
    """Show the passages a method finds for one question."""
    from disease_division.embed import FastEmbedder
    from disease_division.search import search

    documents = load_documents(kb)
    passages = {p.id: p for p in all_passages(documents)}
    conn = _open_store()
    if conn is None:
        return 1
    embedder = FastEmbedder()
    with conn:
        if not _store_matches(conn, documents, embedder.model):
            return 1
        ranking = search(conn, embedder, question, method)[:top]
    print(f"{method} search: {question}\n")
    for rank, passage_id in enumerate(ranking, start=1):
        p = passages[passage_id]
        where = f"{p.title} / {p.heading}" if p.heading else p.title
        text = " ".join(p.text.split())
        print(f"{rank}. [{passage_id}] {where}\n   {text[:110]}{'...' if len(text) > 110 else ''}")
    return 0


def score(kb: Path, questions_path: Path, out: Path) -> int:
    """Score every method on the golden set and write the results."""
    from disease_division import score as scoring
    from disease_division.embed import FastEmbedder

    documents = load_documents(kb)
    questions = load_questions(questions_path)
    conn = _open_store()
    if conn is None:
        return 1
    embedder = FastEmbedder()
    with conn:
        if not _store_matches(conn, documents, embedder.model):
            return 1
        rows = scoring.run(conn, embedder, questions, documents)
    scoring.write(rows, out, embedder.model)
    print(scoring.report(rows, embedder.model))
    print(f"Written to {out / 'retrieval.md'} and {out / 'retrieval.csv'}.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="division", description="The Disease Division")
    commands = parser.add_subparsers(dest="command", required=True)
    shelf_parser = commands.add_parser("shelf", help="report on the stacks and check every rule")
    shelf_parser.add_argument("--kb", type=Path, default=Path("kb"))
    shelf_parser.add_argument("--questions", type=Path, default=Path("evals/questions.toml"))
    load_parser = commands.add_parser("load", help="embed every passage and store it")
    load_parser.add_argument("--kb", type=Path, default=Path("kb"))
    search_parser = commands.add_parser("search", help="show what a search finds for a question")
    search_parser.add_argument("question")
    search_parser.add_argument("--method", choices=METHODS, default="hybrid")
    search_parser.add_argument("--top", type=int, default=5)
    search_parser.add_argument("--kb", type=Path, default=Path("kb"))
    score_parser = commands.add_parser("score", help="score every search method on the golden set")
    score_parser.add_argument("--kb", type=Path, default=Path("kb"))
    score_parser.add_argument("--questions", type=Path, default=Path("evals/questions.toml"))
    score_parser.add_argument("--out", type=Path, default=Path("results"))
    args = parser.parse_args(argv)
    if args.command == "shelf":
        return shelf(args.kb, args.questions)
    if args.command == "load":
        return load(args.kb)
    if args.command == "search":
        return find(args.question, args.method, args.kb, args.top)
    return score(args.kb, args.questions, args.out)


if __name__ == "__main__":
    sys.exit(main())
