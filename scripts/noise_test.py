"""Does any score move when every vector is nudged by a hair?

Two computers compute the same embeddings very slightly differently. If a score depended on
differences that small, the committed results would not survive another machine. This loads the
store with every passage and question vector nudged by Gaussian noise, rescoring for four seeds
at each size, and reports any count or rank that moves. It leaves the store as the real model
made it.

    uv run python scripts/noise_test.py
"""

from pathlib import Path

import numpy as np

from disease_division import score as scoring
from disease_division import store
from disease_division.embed import FastEmbedder
from disease_division.golden import load_questions
from disease_division.kb import load_documents

ROOT = Path(__file__).resolve().parents[1]
SIZES = (1e-5, 1e-4, 1e-3)
SEEDS = (1, 2, 3, 4)


class Nudged:
    def __init__(self, base, size, seed):
        self.base, self.model, self.size = base, base.model, size
        self.rng = np.random.default_rng(seed)

    def _nudge(self, v):
        v = v + self.rng.normal(0, self.size, v.shape).astype(np.float32)
        return v / np.linalg.norm(v)

    def passages(self, texts):
        return [self._nudge(v) for v in self.base.passages(texts)]

    def question(self, text):
        return self._nudge(self.base.question(text))


def measure(conn, embedder, questions, documents):
    store.load(conn, documents, embedder)
    rows = scoring.run(conn, embedder, questions, documents)
    counts = {
        m: [scoring.count(rows, m, k) for k in (1, scoring.K, scoring.DEPTH)]
        for m in scoring.METHODS
    }
    return counts, {r.id: r.ranks for r in rows}


def main() -> None:
    documents = load_documents(ROOT / "kb")
    questions = load_questions(ROOT / "evals" / "questions.toml")
    base = FastEmbedder()
    with store.connect() as conn:
        counts, ranks = measure(conn, base, questions, documents)
        print(f"As the model made them: {counts}")
        for size in SIZES:
            for seed in SEEDS:
                c, r = measure(conn, Nudged(base, size, seed), questions, documents)
                moved = sorted(q for q in r if r[q] != ranks[q])
                print(
                    f"nudge {size:g}, seed {seed}: counts {'unchanged' if c == counts else c};"
                    f" ranks moved: {', '.join(moved) or 'none'}"
                )
        store.load(conn, documents, base)


if __name__ == "__main__":
    main()
