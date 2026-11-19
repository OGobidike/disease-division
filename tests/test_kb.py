"""Reading pages and cutting them into passages."""

import pytest

from disease_division.kb import load_documents, parse_document, split_passages

PAGE = """+++
id = "cabin-baggage"
title = "Cabin baggage"
source = "staff"
visibility = "public"
+++

Every passenger may bring one cabin bag.

## Cabin bag

No more than 7 kg.

## Empty section

## Too big at the gate

It goes in the hold for NGN 6,000.
"""


def test_a_page_is_read_with_its_labels():
    document = parse_document(PAGE)
    assert (document.id, document.source, document.visibility) == (
        "cabin-baggage",
        "staff",
        "public",
    )
    assert document.body.startswith("Every passenger")


def test_windows_line_endings_are_read_the_same():
    assert parse_document(PAGE.replace("\n", "\r\n")) == parse_document(PAGE)


@pytest.mark.parametrize(
    "broken, complaint",
    [
        (PAGE.replace("+++\nid", "id", 1), "must start with"),
        (PAGE.replace('source = "staff"', 'source = "rumour"'), "source must be"),
        (PAGE.replace('visibility = "public"', 'visibility = "secret"'), "visibility must be"),
        (PAGE.replace('title = "Cabin baggage"\n', ""), "missing ['title']"),
        (PAGE.replace('title = "Cabin baggage"', 'title = "x"\nauthor = "y"'), "unexpected"),
        (PAGE.split("+++\n\n")[0] + "+++\n\n", "no text"),
    ],
)
def test_a_broken_page_is_refused_with_a_reason(broken, complaint):
    with pytest.raises(ValueError, match=complaint.replace("[", r"\[").replace("]", r"\]")):
        parse_document(broken)


def test_a_page_is_cut_at_its_headings_and_empty_sections_are_dropped():
    passages = split_passages(parse_document(PAGE))
    assert [p.id for p in passages] == ["cabin-baggage#1", "cabin-baggage#2", "cabin-baggage#3"]
    assert [p.heading for p in passages] == ["", "Cabin bag", "Too big at the gate"]
    assert passages[2].text == "It goes in the hold for NGN 6,000."


def test_search_sees_the_title_and_heading_with_each_passage():
    passage = split_passages(parse_document(PAGE))[2]
    assert (
        passage.searchable
        == "Cabin baggage\nToo big at the gate\nIt goes in the hold for NGN 6,000."
    )


def test_a_page_id_must_match_its_file_name(tmp_path):
    (tmp_path / "wrong-name.md").write_text(PAGE, encoding="utf-8")
    with pytest.raises(ValueError, match="must match the file name"):
        load_documents(tmp_path)


def test_an_empty_folder_is_refused(tmp_path):
    with pytest.raises(ValueError, match="no pages found"):
        load_documents(tmp_path)
