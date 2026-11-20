"""Turning text into vectors, so passages can be found by meaning.

The model is BAAI/bge-small-en-v1.5, the same one Morning Manna uses, run by FastEmbed on ONNX
Runtime (no PyTorch). It downloads once (about 65 MB) into the same cache folder Morning Manna
uses, so a machine that already has it downloads nothing.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable, Protocol

import numpy as np

MODEL = "BAAI/bge-small-en-v1.5"
DIMENSIONS = 384
# BGE was trained to see short questions with this prefix when searching longer passages.
QUESTION_PREFIX = "Represent this sentence for searching relevant passages: "


class Embedder(Protocol):
    model: str

    def passages(self, texts: Iterable[str]) -> list[np.ndarray]: ...

    def question(self, text: str) -> np.ndarray: ...


def cache_dir() -> str:
    return os.environ.get("FASTEMBED_CACHE_PATH", str(Path.home() / ".cache" / "fastembed"))


class FastEmbedder:
    """The real model. Loaded on first use, because loading it takes a second or two."""

    model = MODEL

    def __init__(self) -> None:
        self._engine = None

    def _load(self):
        if self._engine is None:
            from fastembed import TextEmbedding

            self._engine = TextEmbedding(self.model, cache_dir=cache_dir())
        return self._engine

    def passages(self, texts: Iterable[str]) -> list[np.ndarray]:
        return [np.asarray(v, dtype=np.float32) for v in self._load().embed(list(texts))]

    def question(self, text: str) -> np.ndarray:
        (vector,) = self._load().embed([QUESTION_PREFIX + text])
        return np.asarray(vector, dtype=np.float32)
