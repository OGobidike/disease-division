"""The store: every passage in Postgres, with its vector for meaning and its index for keywords.

The database runs in Docker (see docker-compose.yml) on port 5433, so it can sit beside Morning
Manna's, which uses 5432. Set DIVISION_DB_URL to point somewhere else.
"""

from __future__ import annotations

import os

import psycopg
from pgvector.psycopg import register_vector

from disease_division.embed import DIMENSIONS, Embedder
from disease_division.kb import Document, all_passages

DEFAULT_URL = "postgresql://division:division@localhost:5433/division"

SCHEMA = f"""
create table if not exists passages (
    id text primary key,
    doc_id text not null,
    title text not null,
    heading text not null,
    text text not null,
    source text not null,
    visibility text not null,
    model text not null,
    embedding vector({DIMENSIONS}) not null,
    -- Keyword search reads the same words the model reads: title, heading and text.
    search tsvector generated always as (
        to_tsvector('english', title || ' ' || heading || ' ' || text)
    ) stored
);
create index if not exists passages_search on passages using gin (search);
"""


def url() -> str:
    return os.environ.get("DIVISION_DB_URL", DEFAULT_URL)


def connect(address: str | None = None, **options) -> psycopg.Connection:
    """Open a connection with pgvector's types known, so vectors come back as arrays, not text."""
    conn = psycopg.connect(address or url(), **options)
    conn.execute("create extension if not exists vector")
    conn.commit()
    register_vector(conn)
    return conn


def create(conn: psycopg.Connection) -> None:
    conn.execute(SCHEMA)
    conn.commit()


def load(conn: psycopg.Connection, documents: list[Document], embedder: Embedder) -> int:
    """Replace everything in the store with these pages, in one transaction. Returns the count."""
    passages = all_passages(documents)
    vectors = embedder.passages(p.searchable for p in passages)
    by_id = {d.id: d for d in documents}
    create(conn)
    with conn.transaction():
        conn.execute("delete from passages")
        with conn.cursor() as cur:
            cur.executemany(
                "insert into passages (id, doc_id, title, heading, text, source, visibility,"
                " model, embedding) values (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                [
                    (
                        p.id,
                        p.doc_id,
                        p.title,
                        p.heading,
                        p.text,
                        by_id[p.doc_id].source,
                        by_id[p.doc_id].visibility,
                        embedder.model,
                        vector,
                    )
                    for p, vector in zip(passages, vectors, strict=True)
                ],
            )
    return len(passages)


def stored(conn: psycopg.Connection) -> dict[str, tuple[str, str]]:
    """Every stored passage's text and model, by id. Empty if the store was never loaded."""
    exists = conn.execute("select to_regclass('passages') is not null").fetchone()[0]
    if not exists:
        return {}
    return {
        row[0]: (row[1], row[2]) for row in conn.execute("select id, text, model from passages")
    }
