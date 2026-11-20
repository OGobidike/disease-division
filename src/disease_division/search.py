"""Three ways to find passages for a question.

The settings are Morning Manna's, fixed before any search here ran, and never tuned on these
questions: BGE's question prefix, exact cosine search, keyword search that matches any word,
and reciprocal rank fusion with the standard constant of 60.
"""

from __future__ import annotations

import psycopg

from disease_division.embed import Embedder

METHODS = ("meaning", "keyword", "hybrid")
POOL = 50  # how many of each list go into the fusion
RRF_K = 60  # reciprocal rank fusion's standard constant


def by_meaning(conn: psycopg.Connection, vector, limit: int = POOL) -> list[str]:
    """Nearest passages by cosine distance. Exact: with 150 passages, no index is needed."""
    rows = conn.execute(
        "select id from passages order by embedding <=> %s, id limit %s", (vector, limit)
    )
    return [row[0] for row in rows]


def by_keyword(conn: psycopg.Connection, question: str, limit: int = POOL) -> list[str]:
    """Postgres full-text search, matching any of the question's words, best match first."""
    rows = conn.execute(
        """
        with q as (
            select to_tsquery('english',
                replace(plainto_tsquery('english', %(question)s)::text, '&', '|')) as query
        )
        select p.id from passages p, q
        where p.search @@ q.query
        order by ts_rank_cd(p.search, q.query) desc, p.id
        limit %(limit)s
        """,
        {"question": question, "limit": limit},
    )
    return [row[0] for row in rows]


def fuse(*rankings: list[str], k: int = RRF_K) -> list[str]:
    """Reciprocal rank fusion: each list gives 1 / (k + rank) to every passage it holds."""
    scores: dict[str, float] = {}
    best: dict[str, int] = {}
    for ranking in rankings:
        for rank, passage_id in enumerate(ranking, start=1):
            scores[passage_id] = scores.get(passage_id, 0.0) + 1.0 / (k + rank)
            best[passage_id] = min(best.get(passage_id, rank), rank)
    return sorted(scores, key=lambda p: (-scores[p], best[p], p))


def search(
    conn: psycopg.Connection, embedder: Embedder, question: str, method: str = "hybrid"
) -> list[str]:
    if method == "meaning":
        return by_meaning(conn, embedder.question(question))
    if method == "keyword":
        return by_keyword(conn, question)
    if method == "hybrid":
        return fuse(by_meaning(conn, embedder.question(question)), by_keyword(conn, question))
    raise ValueError(f"method must be one of {METHODS}, not {method!r}")
