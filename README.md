# 📚 The Disease Division

**A question-answering system I attack on purpose, then defend, with every result checked by code.**

Companies now put assistants in front of their own documents: a help desk bot reads the policy pages and answers customers. The weak point is that the assistant trusts whatever it reads. One planted document can make it quote a false fee, leak a private note or send a customer to the wrong address.

This repo builds such an assistant, poisons its knowledge base, and measures how often each attack works before and after each defense.

The name comes from a picture of a library with one division set apart for its dangerous books. Here the dangerous books are the planted documents.

I'm building it for two kinds of people:

- **Anyone who ships an assistant like this** and wants to see how it fails, in numbers.
- **Anyone learning to test AI systems.** Every attack and every score here can be rerun with one command.

## 🗺️ Where it stands

It doesn't answer questions yet, but it finds where the answers live. The shelves hold 59 help pages for a made-up airline, 60 frozen questions test against them, and the first score is in.

| Phase | What it ships | Status |
| --- | --- | --- |
| 0. Ground | The [blueprint](docs/BLUEPRINT.md), tooling and CI | ✅ Done |
| 1. The stacks | The knowledge base, the golden questions and their audit, two kinds of search, and the [first score](results/retrieval.md) | ✅ Done |
| 2. The librarian | Answers that cite their passage, and an API | Next |
| 3. The diseased books | The attacks, measured on the undefended system | Planned |
| 4. The quarantine | The defenses, measured one at a time | Planned |
| 5. The telling | The results, written up | Planned |

The [blueprint](docs/BLUEPRINT.md) holds the full plan: the knowledge base, how answers are scored, the six attack families, the six defenses, the cost and the limits.

## 📚 The stacks

The assistant answers for **Zuma Air**, a regional airline I made up, flying from Abuja to six cities. Its help desk lives in [`kb/`](kb): 59 short pages on fares, baggage, refunds, delays and the Summit Club loyalty scheme.

The airline is invented on purpose. No model has read about it, so a right answer proves the system found the page, and every fee is one exact number that code can check.

| Pages | Written by | Who may read them | Why they're there |
| --- | --- | --- | --- |
| 50 | Zuma Air staff | Anyone | The help desk itself |
| 5 | Zuma Air staff | Staff only | Internal guides. Every section ends with the page's own control number, so a leak shows up in code |
| 4 | Outsiders (2 web pages, 2 emails) | Anyone | True, useful pages from untrusted sources, so distrusting outsiders has a measurable cost |

The questions live in [`evals/questions.toml`](evals/questions.toml):

| Questions | Kind | What a good assistant does |
| --- | --- | --- |
| 40 | Answerable | Answers from the right page |
| 8 | Staff only | Declines: the answer is on an internal page |
| 12 | No answer | Says the help desk doesn't cover it |

Every answerable question quotes, word for word, the sentence that answers it. Code checks that the quote exists exactly once, on the page named, and states every fact in the expected answer. Answers are read the way people write them: "N9,000", "9000" and "NGN 9,000" are the same fact. For the no-answer questions, code checks that their key words appear nowhere on the shelves.

A model drafted the pages and the questions. Before the freeze, a second model that had not seen the drafting audited all 60 and flagged 35; I decided each fix, and [the audit](docs/AUDIT.md) records what changed. The questions are then frozen with a checksum before any search runs, and never edited after seeing results.

Zuma Air, its staff, its partners and everyone on its pages are invented. Real airports, agencies and laws appear only as the setting.

## 🔍 The first score

For each of the 48 questions that have an answer on the shelves: is the passage that answers it among the first five results?

| Search | Right passage first | In the top 5 |
| --- | --- | --- |
| By meaning (BGE embeddings in pgvector) | 35 of 48 (73%) | **46 of 48 (96%)** |
| By keyword (Postgres full-text) | 20 of 48 (42%) | 35 of 48 (73%) |
| Hybrid (both, fused by rank) | 33 of 48 (69%) | 43 of 48 (90%) |

The search settings were fixed before this ran and never tuned on these questions. The [full results](results/retrieval.md) and [every question's rank](results/retrieval.csv) are in `results/`.

What it shows:

- **Meaning wins, and adding keywords makes it worse.** When keyword search misses a passage, fusing its list pushes good meaning results down. One question's answer was 2nd by meaning and fell out of the top 10 once fused. In my Morning Manna search, too, hybrid didn't help.
- **Two questions beat every method, for reasons worth knowing.** "Can I call you at 11 at night?" needs the hours "6:00 to 22:00", and the model doesn't connect "11 at night" with "22:00" (the right passage ranks 26th). "What do I need to reach the top Summit Club level?" needs two steps: learn that Monolith is the top, then find its threshold (12th).
- **Nothing keeps staff-only pages from the public yet.** Every staff-only answer is found by meaning, and for "Can I call you at 11 at night?", a staff-only page ranks 4th. Phase 4's permission defense exists for exactly this.
- **The numbers survive another computer.** Two machines compute embeddings very slightly differently. [`scripts/noise_test.py`](scripts/noise_test.py) nudges every vector and rescores, over four seeds at three sizes. At the two smaller sizes nothing moved at all; at the largest, no count moved and only a single question's rank shifted, inside the top 10.

## 🚀 Try it

You need [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/OGobidike/disease-division.git
cd disease-division
uv sync
uv run pytest
uv run division shelf
```

`division shelf` counts what is on the shelves and runs every check on the pages and the questions.

To search, you also need Docker. The database is Postgres 16 with pgvector, on port 5433:

```bash
docker compose up -d --wait db
uv run division load
uv run division search "can I bring my guitar on board"
uv run division score
```

`load` embeds all 150 passages (the model downloads once, about 65 MB). `search` shows what a method finds for any question you type; add `--method meaning`, `keyword` or `hybrid`. `score` rebuilds `results/`.

## ✅ Tested

- ✅ **84 tests**, run by CI on every push and pull request
- ✅ **The store tests run against a real Postgres with pgvector**, each in a throwaway database, created for the test and dropped after it. CI starts its own database and fails if it can't reach it; on a laptop without one, those 9 tests skip.
- ✅ **The golden set is frozen.** A test checks the checksums of the questions and the pages, set before the first search ran.
- ✅ **Every check on the golden set is tested against the fault it exists to catch**: a quote that isn't on its page, a quote found twice, a fact the quote doesn't state, a staff answer pointing at a public page, a "no answer" question the shelves actually answer
- ✅ **No test can reach the network.** A fixture fails any test that tries, so later phases can't spend money by accident.
- ✅ `ruff check` and `ruff format --check` pass
