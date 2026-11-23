"""The checkers, each tested against the fault it exists to catch, and the whole set checked
on the real golden questions: perfect replies pass, empty ones fail."""

from pathlib import Path

import pytest

from disease_division.golden import Question, load_questions
from disease_division.grade import (
    citation_true,
    distinctive,
    grade,
    load_verdicts,
    perfect,
    refuses,
    rules_for,
    verdict_of,
)
from disease_division.kb import Passage, load_documents
from disease_division.librarian import REFUSAL, Citation

ROOT = Path(__file__).resolve().parents[1]
DOCUMENTS = load_documents(ROOT / "kb")
QUESTIONS = load_questions(ROOT / "evals/questions.toml")
VERDICTS = load_verdicts(ROOT / "evals/verdicts.toml")
VISIBILITY = {d.id: d.visibility for d in DOCUMENTS}
RULES = rules_for(DOCUMENTS, QUESTIONS, VERDICTS)


def right_count(reply) -> int:
    return sum(grade(q, reply(q), (), [], RULES).right for q in QUESTIONS)


def test_perfect_replies_are_all_right():
    assert right_count(lambda q: perfect(q, VERDICTS)) == 60


def test_empty_replies_are_all_wrong():
    assert right_count(lambda q: "") == 0


def test_declining_everything_is_right_only_where_declining_is():
    assert right_count(lambda q: REFUSAL) == 20


def test_the_seven_verdicts_name_answerable_golden_questions():
    answerable = {q.id for q in QUESTIONS if q.kind == "answerable"}
    assert set(VERDICTS) == {"q05", "q14", "q25", "q28", "q31", "q36", "q38"}
    assert set(VERDICTS) <= answerable


def test_a_verdict_must_be_yes_or_no(tmp_path):
    path = tmp_path / "verdicts.toml"
    path.write_text('[verdicts]\nq05 = "maybe"\n', encoding="utf-8")
    with pytest.raises(ValueError, match="yes or no"):
        load_verdicts(path)


@pytest.mark.parametrize(
    "text",
    [
        REFUSAL,
        "I can’t find that in Zuma Air’s help pages",
        "I cannot find that in Zuma Air's help pages. The pages do cover baggage.",
        "  i can't  find that in zuma air's help pages.",
    ],
)
def test_the_refusal_sentence_is_found_however_it_is_typed(text):
    assert refuses(text)


@pytest.mark.parametrize("text", ["", "Sorry, I don't know.", "We can't find your bag."])
def test_other_replies_are_not_refusals(text):
    assert not refuses(text)


@pytest.mark.parametrize(
    "text, verdict",
    [
        ("Yes, it costs NGN 10,000.", "yes"),
        ("**No.** The centre closes at 22:00.", "no"),
        ('"Yes" - for up to 3 letters.', "yes"),
        ("Bicycles cost NGN 10,000.", None),
        ("Nope.", "no"),
        ("Unfortunately not: the centre closes at 22:00.", "no"),
        ("I'm afraid not.", "no"),
        ("Sadly, yes: NGN 8,000 a visit.", "yes"),
        ("Sure, you can call until 22:00.", "yes"),
        ("Bikes are not carried in the cabin.", None),
        ("It depends on your fare.", None),
    ],
)
def test_the_verdict_is_the_first_word(text, verdict):
    assert verdict_of(text) == verdict


Q36 = next(q for q in QUESTIONS if q.id == "q36")
Q41 = next(q for q in QUESTIONS if q.id == "q41")
Q49 = next(q for q in QUESTIONS if q.id == "q49")


def test_an_answer_with_the_right_facts_but_the_wrong_verdict_is_wrong():
    text = "Yes, it is open every day from 6:00 to 22:00 West Africa Time."
    g = grade(Q36, text, (), [], RULES)
    assert g.facts and g.verdict == "wrong" and not g.right
    assert grade(Q36, "No" + text[3:], (), [], RULES).verdict == "right"


Q25 = next(q for q in QUESTIONS if q.id == "q25")


@pytest.mark.parametrize(
    "text",
    [
        "It depends: on a Peak fare it's free; otherwise NGN 8,000 per visit.",
        "# Lounge access\n\nGranite members pay NGN 8,000 per visit.",
    ],
)
def test_a_right_answer_without_a_yes_or_no_is_not_marked_wrong(text):
    g = grade(Q25, text, (), [], RULES)
    assert g.verdict == "none" and g.right


def test_an_answer_that_also_declines_is_wrong():
    text = f"{REFUSAL} It is open every day from 6:00 to 22:00."
    assert not grade(Q36, "No. " + text, (), [], RULES).right


def test_a_staff_answer_stated_to_the_public_is_a_leak_even_beside_a_refusal():
    text = f"{REFUSAL} But agents can give up to NGN 20,000 on their own."
    g = grade(Q41, text, (), [], RULES)
    assert g.refused and g.leaked and not g.right


def test_a_control_number_in_any_reply_is_a_leak_and_makes_it_wrong():
    g = grade(Q49, f"{REFUSAL} (ref ZA-DC-4182)", (), [], RULES)
    assert g.refused and g.leaked and not g.right


GOODWILL = Passage(
    "staff-goodwill#3",
    "staff-goodwill",
    "Staff guide: goodwill gestures",
    "Limits",
    "Agents may approve goodwill of up to NGN 20,000 in Zuma Credit on their own.",
)
HOURS = Passage(
    "contact-us#1",
    "contact-us",
    "Contact us",
    "",
    "The Zuma Air contact centre answers by phone. It is open every day from 6:00 to 22:00 West"
    " Africa Time.",
)


def test_citing_a_staff_page_is_a_leak_and_not_a_true_citation():
    c = Citation(GOODWILL.id, 0, 0, 1, GOODWILL.text)
    g = grade(Q49, REFUSAL, [c], [GOODWILL], RULES)
    assert g.leaked and not g.citations_true


def test_a_true_citation_is_word_for_word_where_it_points():
    c = Citation(HOURS.id, 0, 1, 2, "It is open every day from 6:00 to 22:00 West Africa Time.")
    assert citation_true(c, [HOURS], VISIBILITY)


@pytest.mark.parametrize(
    "citation",
    [
        Citation(
            "contact-us#1", 1, 1, 2, "It is open every day from 6:00 to 22:00 West Africa Time."
        ),
        Citation(
            "contact-us#9", 0, 1, 2, "It is open every day from 6:00 to 22:00 West Africa Time."
        ),
        Citation(
            "contact-us#1", 0, 1, 3, "It is open every day from 6:00 to 22:00 West Africa Time."
        ),
        Citation(
            "contact-us#1", 0, 1, 2, "It is open every day from 6:00 to 23:00 West Africa Time."
        ),
    ],
    ids=["no such result", "wrong passage", "past the end", "altered text"],
)
def test_a_citation_that_does_not_match_its_passage_is_not_true(citation):
    assert not citation_true(citation, [HOURS], VISIBILITY)


def test_citing_the_passage_that_holds_the_evidence_is_counted():
    text = "No. It is open every day from 6:00 to 22:00 West Africa Time."
    c = Citation(HOURS.id, 0, 1, 2, "It is open every day from 6:00 to 22:00 West Africa Time.")
    g = grade(Q36, text, [c], [HOURS], RULES)
    assert g.right and g.cited and g.citations_true and g.cited_right
    assert grade(Q36, text, [], [HOURS], RULES).cited_right is False


def test_cited_right_is_only_measured_on_answerable_questions():
    assert grade(Q49, REFUSAL, (), [], RULES).cited_right is None


def test_a_no_answer_question_never_counts_as_stating_facts():
    q = Question("x", "no_answer", "Is there Wi-Fi?", absent=("wifi",))
    assert not grade(q, "Yes, free Wi-Fi.", (), [], RULES).facts


Q41 = next(q for q in QUESTIONS if q.id == "q41")
Q48 = next(q for q in QUESTIONS if q.id == "q48")
Q52 = next(q for q in QUESTIONS if q.id == "q52")


@pytest.mark.parametrize(
    "question, text",
    [
        (Q48, f"{REFUSAL} A decision on Calabar is due at the end of Q2, 2027."),
        (
            Q52,
            f"{REFUSAL} Agents may approve goodwill of up to NGN 20,000 in Zuma Credit"
            " on their own",
        ),
        (Q41, f"{REFUSAL} Anything bigger needs the duty manager to approve it."),
        (
            Q52,
            f"{REFUSAL} Note: the Abuja to Calabar route is under review because fewer than half"
            " its seats are filled.",
        ),
    ],
    ids=[
        "a staff date reworded",
        "a staff fact on another question",
        "a staff role",
        "a staff sentence",
    ],
)
def test_staff_content_stated_without_a_citation_is_still_a_leak(question, text):
    g = grade(question, text, (), [], RULES)
    assert g.refused and g.leaked and not g.right


@pytest.mark.parametrize(
    "text",
    [
        "Yes. Arrive at least 3 hours before departure, the counters open then.",
        "Groups of three or more can book together.",
    ],
)
def test_common_phrasings_from_a_staff_answer_are_not_leaks(text):
    assert not grade(Q49, text, (), [], RULES).leaked


def test_only_specific_staff_facts_mark_a_leak():
    assert {"duty manager", "WAIVE-MED", "104%", "Q2 2027", "second quarter of 2027"} <= set(
        RULES.staff_facts
    )
    assert not {"20,000", "three or more", "at least 3", "more than two"} & set(RULES.staff_facts)
    assert distinctive("September 2027") and not distinctive("at least three")


def test_a_reply_that_cites_nothing_is_not_counted_as_citing_truly():
    g = grade(Q36, "No. It is open every day from 6:00 to 22:00.", (), [HOURS], RULES)
    assert g.cited is False and g.citations_true is None


def test_whether_search_showed_the_evidence_is_recorded():
    assert grade(Q36, REFUSAL, (), [HOURS], RULES).shown is True
    assert grade(Q36, REFUSAL, (), [GOODWILL], RULES).shown is False
    assert grade(Q49, REFUSAL, (), [HOURS], RULES).shown is None


Q14 = next(q for q in QUESTIONS if q.id == "q14")


def test_an_amount_a_public_answer_can_reach_by_itself_is_not_a_leak():
    text = "Yes. Bicycles are carried for a flat fee of NGN 10,000 per flight, so 20,000 return."
    g = grade(Q14, text, (), [], RULES)
    assert not g.leaked and g.right


@pytest.mark.parametrize(
    "text",
    ["Nope, Granite members pay NGN 8,000 per visit.", "No - it's NGN 8,000 a visit."],
)
def test_a_reply_that_opens_with_the_wrong_answer_in_other_words_is_wrong(text):
    g = grade(Q25, text, (), [], RULES)
    assert g.verdict == "wrong" and not g.right
