# 📚 The Disease Division

**A question-answering system I attack on purpose, then defend, with every result checked by code.**

Companies now put assistants in front of their own documents: a help desk bot reads the policy pages and answers customers. The weak point is that the assistant trusts whatever it reads. One planted document can make it quote a false fee, leak a private note or send a customer to the wrong address.

This repo builds such an assistant, poisons its knowledge base, and measures how often each attack works before and after each defense.

The name comes from a picture of a library with one division set apart for its dangerous books. Here the dangerous books are the planted documents.

I'm building it for two kinds of people:

- **Anyone who ships an assistant like this** and wants to see how it fails, in numbers.
- **Anyone learning to test AI systems.** Every attack and every score here can be rerun with one command.

## 🗺️ Where it stands

Nothing here answers a question yet. The plan is written, the ground is laid, and the shelves are stocked: 59 help pages for a made-up airline and 60 questions to test against them.

| Phase | What it ships | Status |
| --- | --- | --- |
| 0. Ground | The [blueprint](docs/BLUEPRINT.md), tooling and CI | ✅ Done |
| 1. The stacks | The knowledge base and the golden questions (Card D1), then two kinds of search and the first score (Card D2) | 🔨 Under way |
| 2. The librarian | Answers that cite their passage, and an API | Planned |
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

## ✅ Tested

- ✅ **62 tests**, run by CI on every push and pull request
- ✅ **Every check on the golden set is tested against the fault it exists to catch**: a quote that isn't on its page, a quote found twice, a fact the quote doesn't state, a staff answer pointing at a public page, a "no answer" question the shelves actually answer
- ✅ **No test can reach the network.** A fixture fails any test that tries, so later phases can't spend money by accident.
- ✅ `ruff check` and `ruff format --check` pass
