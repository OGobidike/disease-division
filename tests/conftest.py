"""Rules every test runs under: no key, no network and no money."""

import socket

import pytest


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Fail any test that tries to open a network connection."""

    def refuse(*args, **kwargs):
        raise AssertionError("a test tried to reach the network")

    monkeypatch.setattr(socket.socket, "connect", refuse)


class FakeEmbedder:
    """A stand-in for the model: each word lights one of 384 slots, so shared words mean close
    vectors. Deterministic, instant, and it never downloads anything."""

    model = "fake-words-384"

    def _vector(self, text):
        import hashlib
        import re

        import numpy as np

        v = np.zeros(384, dtype=np.float32)
        for word in re.findall(r"[a-z0-9]+", text.lower()):
            v[int(hashlib.md5(word.encode()).hexdigest(), 16) % 384] += 1.0
        norm = np.linalg.norm(v)
        return v / norm if norm else v

    def passages(self, texts):
        return [self._vector(t) for t in texts]

    def question(self, text):
        return self._vector(text)


@pytest.fixture
def fake_embedder():
    return FakeEmbedder()


@pytest.fixture
def db():
    """A connection to a throwaway database, created for the test and dropped after it, so the
    real store is never touched or even visible. Skipped when no database is running, unless
    DIVISION_REQUIRE_DB is set (as in CI), where a missing database fails the run."""
    import os
    import uuid

    import psycopg
    from psycopg.conninfo import make_conninfo

    from disease_division import store

    try:
        admin = psycopg.connect(store.url(), autocommit=True, connect_timeout=3)
    except psycopg.OperationalError as error:
        if os.environ.get("DIVISION_REQUIRE_DB"):
            raise
        pytest.skip(f"no database ({error.__class__.__name__}): docker compose up -d --wait db")
    name = f"division_test_{uuid.uuid4().hex[:10]}"
    admin.execute(f'create database "{name}"')
    conn = store.connect(make_conninfo(store.url(), dbname=name))
    try:
        yield conn
    finally:
        conn.close()
        admin.execute(f'drop database "{name}"')
        admin.close()
