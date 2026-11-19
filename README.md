# 📚 The Disease Division

**A question-answering system I attack on purpose, then defend, with every result checked by code.**

Companies now put assistants in front of their own documents: a help desk bot reads the policy pages and answers customers. The weak point is that the assistant trusts whatever it reads. One planted document can make it quote a false fee, leak a private note or send a customer to the wrong address.

This repo builds such an assistant, poisons its knowledge base, and measures how often each attack works before and after each defense.

The name comes from a picture of a library with one division set apart for its dangerous books. Here the dangerous books are the planted documents.

I'm building it for two kinds of people:

- **Anyone who ships an assistant like this** and wants to see how it fails, in numbers.
- **Anyone learning to test AI systems.** Every attack and every score here can be rerun with one command.

## 🗺️ Where it stands

Nothing here answers a question yet. The plan is written and the ground is laid.

| Phase | What it ships | Status |
| --- | --- | --- |
| 0. Ground | The [blueprint](docs/BLUEPRINT.md), tooling and CI | ✅ Done |
| 1. The stacks | The knowledge base, two kinds of search, the first score | Next |
| 2. The librarian | Answers that cite their passage, and an API | Planned |
| 3. The diseased books | The attacks, measured on the undefended system | Planned |
| 4. The quarantine | The defenses, measured one at a time | Planned |
| 5. The telling | The results, written up | Planned |

The [blueprint](docs/BLUEPRINT.md) holds the full plan: the knowledge base, how answers are scored, the six attack families, the six defenses, the cost and the limits.

## 🚀 Try it

You need [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/OGobidike/disease-division.git
cd disease-division
uv sync
uv run pytest
```

## ✅ Tested

- ✅ **2 tests**, run by CI on every push and pull request
- ✅ **No test can reach the network.** A fixture fails any test that tries, so later phases can't spend money by accident.
- ✅ `ruff check` and `ruff format --check` pass
