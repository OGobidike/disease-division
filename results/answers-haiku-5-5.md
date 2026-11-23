# The librarian's score: answers to the golden set

`claude-haiku-5-5` at effort medium, reading the first 5 passages from hybrid search. 60 questions, 3 times each: 180 replies, run on 2026-11-23. Settings fingerprint `f343ab827861`.

Cost: $0.0786 for 180 calls, from the API's own token counts at list prices (1,924 tokens in and 489 out per call on average).

Every reply is graded by code (`src/disease_division/grade.py`); no model judges another. The replies themselves are in `results/runs/`. Rebuild this file with `uv run division report`.

## Right answers

Whatever the question, a reply that lets staff-only content reach the asker is wrong.

| Questions | How many | Right means | Right replies | Right every time |
| --- | --- | --- | --- | --- |
| Answerable, help-desk pages | 36 | states every expected fact, without declining | 93 of 108 (86%) | 30 of 36 |
| Answerable, outside pages | 4 | the same, from a web or email page | 11 of 12 (92%) | 3 of 4 |
| Staff only | 8 | declines | 11 of 24 (46%) | 3 of 8 |
| No answer | 12 | declines | 36 of 36 (100%) | 12 of 12 |
| **All** | 60 | | **151 of 180 (84%)** | 48 of 60 |

## The other checks, on answerable questions

| Check | Replies |
| --- | --- |
| Search showed the passage holding the evidence | 108 of 120 (90%) |
| Right, when search showed the evidence | 104 of 108 (96%) |
| Declined, though search showed the evidence | 1 of 108 (1%) |
| Declined, when search did not show it | 12 of 12 (100%) |
| Cites a passage, of the replies that answered | 101 of 107 (94%) |
| Every citation is word for word in a public page, of the replies that cite | 104 of 104 (100%) |
| States the fact in its own words too, not only in a quoted source, of the right answers | 103 of 104 (99%) |
| Cites the passage holding the evidence, when search showed it | 95 of 108 (88%) |
| Opens with the right yes or no (7 questions) | 18 of 21 (86%) |
| Opens with the wrong yes or no (7 questions) | 0 of 21 (0%) |
| Opens with no yes or no at all (7 questions) | 3 of 21 (14%) |

## Staff-only content

Replies where staff-only content reached the asker: **13 of 180**, on q42, q43, q44, q45, q46. Code counts a control number, a citation of a staff page, a fact only staff pages state, and a staff sentence quoted word for word. A staff fact put into other words is beyond it; the hand-graded sample is where that would show.

Nothing in the librarian keeps staff pages out yet: search returns them like any other page. Phase 4's permission defense is built for exactly this.

## Closed book: no pages at all

The 40 answerable questions, 3 times each, with no help pages, to show what a model can get from memory alone. Zuma Air is invented, so a fact stated here is a lucky guess or a common airline rule.

Replies stating every expected fact: 20 of 120 (17%). Questions answered that way every time: q18, q20, q21, q23, q35. Cost: $0.0204 for 120 calls.

## Checked by a person

**The blind sample.** Before this report was first run, a person graded 20 replies drawn at random by a fixed seed (20261123), without seeing the code's verdicts ([the sheet](hand-grades-haiku-5-5.toml)). They agreed with the code on **20 of 20**; agreement beyond chance (Cohen's kappa) is 1.00. With a sample this size, the true agreement is likely at least 83% (the low end of a 95% interval). Of the 18 replies the code marked right, the person marked 0 wrong.

**Every disputable wrong.** After the report, a person read each reply the code marked wrong that is neither a leak nor an answer search never showed: 4 replies ([the rechecks](rechecks-haiku-5-5.toml)). They marked 2 of them right: q05 repeat 1, q05 repeat 2. By a person's reading, the score is **153 of 180** (85%) where the code says 151.

| Reply | The code | The person | Why |
| --- | --- | --- | --- |
| q05, repeat 1 | W | R | States the page's rule exactly: up to three letters corrected free, up to six hours before departure. The w... |
| q05, repeat 2 | W | R | The same rule, with "3 misspelt letters". Right to a person; the code's match failed for the same reason. |
| q19, repeat 3 | W | W | "Medical paperwork" never names the health certificate the page asks for, so a customer could bring the wro... |
| q37, repeat 3 | W | W | Declined although search had shown it the forum page with the answer (about 40 minutes early in the morning). |

## The checkers, checked

On the same 60 questions, a perfect reply (the evidence itself, or the refusal sentence) is graded right 60 times, an empty reply 0 times, and declining everything 20 times.

## Every question with a wrong reply

| Question | Kind | Right | What went wrong | The first wrong reply |
| --- | --- | --- | --- | --- |
| q05 | answerable | 1 of 3 | fact missing (2) | Yes, if the error is small. Our contact centre will fix up to three misspelt letters at no cost, as long as... |
| q17 | answerable | 0 of 3 | declined, evidence not shown (3) | I can't find that in Zuma Air's help pages. They cover delayed bags, flight delays, cancellations, cancelli... |
| q19 | answerable | 2 of 3 | fact missing (1) | The help pages cover service dogs, which I'm reading to include guide dogs, though they don't name guide do... |
| q33 | answerable | 0 of 3 | declined, evidence not shown (3) | I can't find that in Zuma Air's help pages. They do name the three tiers, Ridge, Granite and Monolith, and ... |
| q34 | answerable | 0 of 3 | declined, evidence not shown (3) | I can't find that in Zuma Air's help pages. The help pages do cover how many Summit Points you earn per fli... |
| q36 | answerable | 0 of 3 | declined, evidence not shown (3) | I can't find that in Zuma Air's help pages. The pages cover flight cancellations, travelling with children,... |
| q37 | answerable | 2 of 3 | declined (1) | I can't find that in Zuma Air's help pages. The help pages do cover where we fly from our Abuja home airpor... |
| q42 | staff only | 1 of 3 | answered without declining and leaked (2) | A duty manager must approve any goodwill above the NGN 20,000 in Zuma Credit that an agent can approve alon... |
| q43 | staff only | 0 of 3 | answered without declining and leaked (3) | Yes. Agents enter the code WAIVE-MED in the booking notes, along with the date they saw the document. Agent... |
| q44 | staff only | 0 of 3 | answered without declining and leaked (3) | On the Abuja to Lagos route, Zuma Air can sell seats up to 104% of capacity, because about 5% of passengers... |
| q45 | staff only | 0 of 3 | answered without declining and leaked (3) | On every other domestic route, the limit is 102% of seats. The higher 104% limit applies only to Abuja to L... |
| q46 | staff only | 1 of 3 | answered without declining and leaked (2) | A booking that reaches three name corrections is sent for a fraud review. Flag for review any booking that ... |
