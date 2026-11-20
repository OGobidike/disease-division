"""How the first score is counted and written down."""

from disease_division.golden import Question
from disease_division.kb import Document
from disease_division.score import Row, count, first_right, report, slice_of

TEXTS = {"a#1": "Nothing here.", "b#1": "A bag costs NGN 8,000.", "c#1": "Also nothing."}


def test_the_rank_is_where_the_evidence_first_appears():
    assert first_right(["a#1", "b#1", "c#1"], TEXTS, "A bag costs NGN 8,000.") == 2


def test_evidence_beyond_the_tenth_result_is_not_found():
    ranking = ["a#1"] * 10 + ["b#1"]
    assert first_right(ranking, TEXTS, "A bag costs NGN 8,000.") is None


def test_each_question_falls_in_the_slice_where_its_answer_lives():
    pages = {
        "desk": Document("desk", "D", "staff", "public", "x"),
        "forum": Document("forum", "F", "web", "public", "x"),
        "guide": Document("guide", "G", "staff", "staff", "x"),
    }
    assert slice_of(Question("q1", "answerable", "?", doc="desk"), pages) == "help-desk"
    assert slice_of(Question("q2", "answerable", "?", doc="forum"), pages) == "outside"
    assert slice_of(Question("q3", "staff_only", "?", doc="guide"), pages) == "staff-only"


ROWS = [
    Row("q01", "help-desk", {"meaning": 1, "keyword": 3, "hybrid": 1}),
    Row("q02", "help-desk", {"meaning": 6, "keyword": None, "hybrid": 2}),
    Row("q03", "staff-only", {"meaning": None, "keyword": None, "hybrid": None}),
]


def test_counts_include_the_edge_of_the_window():
    assert count(ROWS, "meaning", 1) == 1
    assert count(ROWS, "keyword", 3) == 1
    assert count(ROWS, "hybrid", 5) == 2


def test_the_report_names_what_every_method_missed():
    text = report(ROWS, "fake")
    assert "| Meaning | 1 of 3 (33%) | 1 of 3 (33%) | 2 of 3 (67%) |" in text
    assert "Not in the top 5 for any method: q03." in text


def test_the_report_holds_no_dates_or_timings_so_reruns_compare_cleanly():
    assert report(ROWS, "fake") == report(ROWS, "fake")
