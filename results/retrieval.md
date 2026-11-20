# The first score: finding the right passage

For each of the 48 questions that have an answer on the shelves, is the passage that answers it among the first results? The 12 no-answer questions have nothing to find, so they wait for Phase 2.

Model: `BAAI/bge-small-en-v1.5`. Search settings were fixed before this ran and never tuned on these questions (see `src/disease_division/search.py`). Rebuild this file with `uv run division score`.

| Method | Right passage first | In the top 5 | In the top 10 |
| --- | --- | --- | --- |
| Meaning | 35 of 48 (73%) | 46 of 48 (96%) | 46 of 48 (96%) |
| Keyword | 20 of 48 (42%) | 35 of 48 (73%) | 37 of 48 (77%) |
| Hybrid | 33 of 48 (69%) | 43 of 48 (90%) | 45 of 48 (94%) |

## In the top 5, by where the answer lives

| Where the answer lives | Questions | Meaning | Keyword | Hybrid |
| --- | --- | --- | --- | --- |
| Help-desk pages (written by Zuma Air staff) | 36 | 34 | 26 | 32 |
| Outside pages (web and email) | 4 | 4 | 4 | 4 |
| Staff-only pages | 8 | 8 | 5 | 7 |

## Missed by every method

Not in the top 5 for any method: q33, q36.

Each question's rank for each method is in `retrieval.csv`.
