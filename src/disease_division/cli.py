"""The `division` command."""

from __future__ import annotations

import argparse
import math
import os
import sys
from collections import Counter
from pathlib import Path

from disease_division.golden import KINDS, check, load_questions
from disease_division.kb import CONTROL_NUMBER, all_passages, load_documents, split_passages
from disease_division.librarian import DEFAULT_MODEL, MODELS, PASSAGES
from disease_division.search import METHODS

QUESTIONS = Path("evals/questions.toml")
PILOT = Path("evals/pilot.toml")
VERDICTS = Path("evals/verdicts.toml")
RUNS = Path("results/runs")


def shelf(kb: Path, questions_path: Path, pilot_path: Path = PILOT, verdicts_path=VERDICTS) -> int:
    """Report what is on the shelves and check every rule. Returns the exit code."""
    from disease_division.grade import load_verdicts

    try:
        documents = load_documents(kb)
        questions = load_questions(questions_path)
        practice = load_questions(pilot_path)
        verdicts = load_verdicts(verdicts_path)
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

    print(
        f"The practice set (for the pilot): {len(practice)} questions;"
        f" yes-or-no verdicts: {len(verdicts)}"
    )

    problems = check(questions, documents)
    problems += [f"practice set: {p}" for p in check(practice, documents)]
    answerable = {q.id for q in questions if q.kind == "answerable"}
    problems += [
        f"{qid}: a verdict needs an answerable golden question"
        for qid in verdicts
        if qid not in answerable
    ]
    passages = all_passages(documents)

    def homes(qs):
        return {p.id for q in qs if q.evidence for p in passages if q.evidence in p.text}

    golden_homes = homes(questions)
    problems += [
        f"practice set: {q.id} is answered in a passage that answers a golden question"
        for q in practice
        if homes([q]) & golden_homes
    ]
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

    if not store.matches(conn, documents, model):
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


# ---- the librarian: the commands that call Claude ---------------------------------------------


def load_env(path: Path = Path(".env")) -> None:
    """Read NAME=value lines from .env into the environment. A name already set wins."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.strip().removeprefix("export ").strip()
        value = value.strip().strip("\"'")
        if name and name not in os.environ:
            os.environ[name] = value


def has_key() -> bool:
    """True when a key is set. Paid commands check this before they do anything else."""
    load_env()
    if os.environ.get("ANTHROPIC_API_KEY"):
        return True
    print(
        "No ANTHROPIC_API_KEY. Copy .env.example to .env and put your key there; .env is never"
        " committed. Set a spend limit in the Claude Console before the first paid run."
    )
    return False


def call_failed(error) -> int:
    """Explain an API error in one line, and say what to do next."""
    import anthropic

    again = "Run the same command again: it picks up where it stopped."
    if isinstance(error, anthropic.AuthenticationError):
        message = "The API refused the key in .env (401). Check it in the Claude Console."
    elif isinstance(error, anthropic.PermissionDeniedError):
        message = f"The key may not use this model (403): {error.message}"
    elif isinstance(error, anthropic.RateLimitError):
        message = f"Still rate limited after the retries (429). Wait a minute. {again}"
    elif isinstance(error, anthropic.BadRequestError):
        message = f"The API turned the request down (400): {error.message}"
    elif isinstance(error, anthropic.APIStatusError):
        message = f"The API answered {error.status_code}: {error.message}. {again}"
    else:
        message = f"Couldn't reach the API ({error.__class__.__name__}). {again}"
    print(message)
    return 1


def retriever(conn, embedder, documents):
    """Search the store the librarian's way: the first PASSAGES results of its method."""
    from disease_division.librarian import METHOD
    from disease_division.search import search

    passages = {p.id: p for p in all_passages(documents)}

    def retrieve(question: str):
        return [passages[i] for i in search(conn, embedder, question, METHOD)[:PASSAGES]]

    return retrieve


def ask(question: str, model_name: str, kb: Path, closed_book: bool) -> int:
    """Ask the librarian one question and show its reply, citations and cost."""
    import anthropic

    from disease_division.embed import FastEmbedder
    from disease_division.librarian import Claude

    if not has_key():
        return 1
    documents = load_documents(kb)
    passages = []
    if not closed_book:
        conn = _open_store()
        if conn is None:
            return 1
        embedder = FastEmbedder()
        with conn:
            if not _store_matches(conn, documents, embedder.model):
                return 1
            passages = retriever(conn, embedder, documents)(question)
    try:
        reply = Claude(model_name).answer(question, passages, closed_book=closed_book)
    except anthropic.APIError as error:
        return call_failed(error)
    print(reply.text or "(no text)")
    for c in reply.citations:
        print(f"  cited [{c.passage}] {c.text}")
    read = "no pages" if closed_book else "read " + ", ".join(p.id for p in passages)
    print(
        f"\n{reply.model} {read}. {reply.input_tokens:,} tokens in, {reply.output_tokens:,} out:"
        f" ${reply.cost:.5f}. Stop reason: {reply.stop_reason}."
    )
    return 0


def run_questions(questions, model_name, kb, path, repeats, budget, closed_book) -> int:
    """Run a question set through the librarian into `path`, within the budget."""
    import anthropic

    from disease_division.embed import FastEmbedder
    from disease_division.librarian import Claude
    from disease_division.run import run

    documents = load_documents(kb)
    model = Claude(model_name)
    print(
        f"{len(questions)} questions x {repeats} to {model_name}"
        f"{', closed book' if closed_book else ''}, budget ${budget:g}, into {path}."
    )
    try:
        if closed_book:
            calls, spent, finished = run(
                questions, model, lambda q: [], path, repeats, budget, closed_book=True
            )
        else:
            conn = _open_store()
            if conn is None:
                return 1
            embedder = FastEmbedder()
            with conn:
                if not _store_matches(conn, documents, embedder.model):
                    return 1
                retrieve = retriever(conn, embedder, documents)
                calls, spent, finished = run(questions, model, retrieve, path, repeats, budget)
    except anthropic.APIError as error:
        return call_failed(error)
    except ValueError as error:
        print(error)
        return 1
    print(f"{calls} calls made now; ${spent:.4f} spent in this run so far.")
    return 0 if finished else 1


def pilot(model_name: str, kb: Path, folder: Path, budget: float) -> int:
    """The 20 practice questions, once each: the real size of a call, before the golden run."""
    from disease_division.librarian import fingerprint
    from disease_division.run import pilot_summary, read_records, run_path

    if not has_key():
        return 1
    questions = load_questions(PILOT)
    path = run_path(folder, "pilot", model_name)
    code = run_questions(questions, model_name, kb, path, 1, budget, closed_book=False)
    records = [r for r in read_records(path) if r.get("settings") == fingerprint(model_name)]
    if records:
        print()
        print(pilot_summary(records, questions))
    return code


def answer(model_name, kb, questions_path, folder, repeats, budget, closed_book) -> int:
    """The golden run: every golden question, `repeats` times. Closed book asks only the
    answerable ones, with no pages."""
    from disease_division.run import run_path

    if not has_key():
        return 1
    questions = load_questions(questions_path)
    if closed_book:
        questions = [q for q in questions if q.kind == "answerable"]
    path = run_path(folder, "closed-book" if closed_book else "golden", model_name)
    code = run_questions(questions, model_name, kb, path, repeats, budget, closed_book)
    if code == 0:
        print("Every reply is in. Next: uv run division report")
    return code


def report(model_name, kb, questions_path, verdicts_path, folder, out) -> int:
    """Grade a model's golden run (and its closed-book run, if there is one) and write it up."""
    from disease_division import run as running
    from disease_division.grade import load_verdicts

    records = running.read_records(running.run_path(folder, "golden", model_name))
    if not records:
        print(f"No golden run for {model_name} yet. Run: uv run division answer")
        return 1
    closed = running.read_records(running.run_path(folder, "closed-book", model_name))
    documents = load_documents(kb)
    questions = load_questions(questions_path)
    verdicts = load_verdicts(verdicts_path)
    tag = running.short(model_name)
    try:
        hand = running.read_marks(out / f"hand-grades-{tag}.toml")
        rechecks = running.read_marks(out / f"rechecks-{tag}.toml")
        text = running.report(records, closed, questions, documents, verdicts, hand, rechecks)
    except ValueError as error:
        print(f"Can't report: {error}.")
        return 1
    out.mkdir(parents=True, exist_ok=True)
    name = f"answers-{tag}"
    (out / f"{name}.md").write_text(text, encoding="utf-8")
    running.write_csv(out / f"{name}.csv", records, questions, documents, verdicts)
    print(text)
    print(f"Written to {out / (name + '.md')} and {out / (name + '.csv')}.")
    return 0


def write_sheet(model_name, questions_path, verdicts_path, folder, out) -> int:
    """Write the blind grading sheet for a finished golden run. Run it before the report, and
    grade the sheet before reading the report, so the code's verdicts are never seen."""
    from disease_division import run as running
    from disease_division.grade import load_verdicts

    path = out / f"hand-grades-{running.short(model_name)}.toml"
    if path.exists():
        print(f"{path} is already there, so it was left as it is.")
        return 1
    records = running.read_records(running.run_path(folder, "golden", model_name))
    questions = load_questions(questions_path)
    wanted = len(questions) * max((r["repeats"] for r in records), default=0)
    if not records or len(records) < wanted:
        print(f"The golden run has {len(records)} of {wanted or '?'} replies, so no sheet was"
              " written. Finish it first: uv run division answer")  # fmt: skip
        return 1
    out.mkdir(parents=True, exist_ok=True)
    path.write_text(running.sheet(records, questions, load_verdicts(verdicts_path)), "utf-8")
    print(f"Wrote {path}: {running.SAMPLE} replies to grade by hand, before reading the report.")
    return 0


def serve(host: str, port: int, kb: Path, budget: float | None) -> int:
    """Run the API. It needs a key and a store that matches the pages, and checks both first."""
    from disease_division import api
    from disease_division.embed import FastEmbedder
    from disease_division.librarian import Claude

    if not has_key():
        return 1
    if budget is None:
        try:
            budget = float(os.environ.get("DIVISION_API_BUDGET", api.DEFAULT_BUDGET))
        except ValueError:
            print("DIVISION_API_BUDGET must be a number of US dollars, such as 1.00.")
            return 1
    if not math.isfinite(budget) or budget <= 0:
        print(f"A budget must be a positive number of US dollars, such as 1.00, not {budget}.")
        return 1
    model = Claude(max_retries=0)  # one request is at most one billed call
    if budget < api.worst_case(model.name):
        print(
            f"A budget of ${budget:g} can't cover one call at its worst case"
            f" (${api.worst_case(model.name):.4f} on {model.name}), so nothing would be answered."
        )
        return 1
    documents = load_documents(kb)
    conn = _open_store()
    if conn is None:
        return 1
    embedder = FastEmbedder()
    with conn:
        if not _store_matches(conn, documents, embedder.model):
            return 1
    import uvicorn

    print(
        f"The librarian is listening on http://{host}:{port} (try /docs). It stops answering"
        f" after ${budget:g}. Ctrl+C to stop."
    )
    uvicorn.run(api.build(documents, embedder, model, budget), host=host, port=port)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="division", description="The Disease Division")
    commands = parser.add_subparsers(dest="command", required=True)
    shelf_parser = commands.add_parser("shelf", help="report on the stacks and check every rule")
    shelf_parser.add_argument("--kb", type=Path, default=Path("kb"))
    shelf_parser.add_argument("--questions", type=Path, default=QUESTIONS)
    shelf_parser.add_argument("--pilot", type=Path, default=PILOT)
    shelf_parser.add_argument("--verdicts", type=Path, default=VERDICTS)
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

    def model_option(p):
        p.add_argument("--model", choices=MODELS, default=DEFAULT_MODEL)
        p.add_argument("--kb", type=Path, default=Path("kb"))

    ask_parser = commands.add_parser("ask", help="ask the librarian one question (paid)")
    ask_parser.add_argument("question")
    ask_parser.add_argument("--closed-book", action="store_true", help="give it no pages")
    model_option(ask_parser)
    pilot_parser = commands.add_parser("pilot", help="the 20 practice questions, once (paid)")
    pilot_parser.add_argument("--budget", type=float, default=0.05, help="US dollars")
    pilot_parser.add_argument("--runs", type=Path, default=RUNS)
    model_option(pilot_parser)
    answer_parser = commands.add_parser("answer", help="answer the golden set (paid)")
    answer_parser.add_argument("--repeats", type=int, default=3)
    answer_parser.add_argument("--budget", type=float, default=0.50, help="US dollars")
    answer_parser.add_argument("--closed-book", action="store_true", help="no pages at all")
    answer_parser.add_argument("--questions", type=Path, default=QUESTIONS)
    answer_parser.add_argument("--runs", type=Path, default=RUNS)
    model_option(answer_parser)
    report_parser = commands.add_parser("report", help="grade a golden run and write it up")
    report_parser.add_argument("--questions", type=Path, default=QUESTIONS)
    report_parser.add_argument("--verdicts", type=Path, default=VERDICTS)
    report_parser.add_argument("--runs", type=Path, default=RUNS)
    report_parser.add_argument("--out", type=Path, default=Path("results"))
    model_option(report_parser)
    serve_parser = commands.add_parser("serve", help="run the API (answers cost money)")
    serve_parser.add_argument("--host", default="127.0.0.1", help="127.0.0.1 is this computer only")
    serve_parser.add_argument("--port", type=int, default=8002)
    serve_parser.add_argument("--budget", type=float, default=None, help="US dollars per run")
    serve_parser.add_argument("--kb", type=Path, default=Path("kb"))
    sheet_parser = commands.add_parser("sheet", help="write the blind hand-grading sheet")
    sheet_parser.add_argument("--questions", type=Path, default=QUESTIONS)
    sheet_parser.add_argument("--verdicts", type=Path, default=VERDICTS)
    sheet_parser.add_argument("--runs", type=Path, default=RUNS)
    sheet_parser.add_argument("--out", type=Path, default=Path("results"))
    model_option(sheet_parser)

    args = parser.parse_args(argv)
    if args.command == "shelf":
        return shelf(args.kb, args.questions, args.pilot, args.verdicts)
    if args.command == "load":
        return load(args.kb)
    if args.command == "search":
        return find(args.question, args.method, args.kb, args.top)
    if args.command == "score":
        return score(args.kb, args.questions, args.out)
    if args.command == "ask":
        return ask(args.question, args.model, args.kb, args.closed_book)
    if args.command == "pilot":
        return pilot(args.model, args.kb, args.runs, args.budget)
    if args.command == "serve":
        return serve(args.host, args.port, args.kb, args.budget)
    if args.command == "sheet":
        return write_sheet(args.model, args.questions, args.verdicts, args.runs, args.out)
    if args.command == "answer":
        return answer(
            args.model,
            args.kb,
            args.questions,
            args.runs,
            args.repeats,
            args.budget,
            args.closed_book,
        )
    return report(args.model, args.kb, args.questions, args.verdicts, args.runs, args.out)


if __name__ == "__main__":
    sys.exit(main())
