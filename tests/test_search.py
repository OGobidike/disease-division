"""Fusing rankings, and the three searches against a real Postgres."""

import pytest

from disease_division import store
from disease_division.kb import parse_document
from disease_division.search import by_keyword, by_meaning, fuse, search


def test_fusion_rewards_a_passage_both_lists_rank_well():
    assert fuse(["a", "b", "c"], ["b", "c", "a"])[0] == "b"


def test_fusion_keeps_a_passage_only_one_list_found():
    assert set(fuse(["a", "b"], ["c"])) == {"a", "b", "c"}


def test_fusion_breaks_ties_the_same_way_every_time():
    assert fuse(["a", "b"], ["b", "a"]) == fuse(["b", "a"], ["a", "b"]) == ["a", "b"]


PAGES = [
    parse_document(
        '+++\nid = "bags"\ntitle = "Cabin baggage"\nsource = "staff"\nvisibility = "public"\n'
        "+++\n\nOne cabin bag of 7 kg.\n\n## Too big\n\nA bag that does not fit costs NGN 6,000.\n"
    ),
    parse_document(
        '+++\nid = "food"\ntitle = "Food on board"\nsource = "staff"\nvisibility = "public"\n'
        "+++\n\nJollof rice with chicken costs NGN 3,500.\n"
    ),
]


@pytest.fixture
def loaded(db, fake_embedder):
    store.load(db, PAGES, fake_embedder)
    return db


def test_loading_twice_leaves_one_copy_of_each_passage(loaded, fake_embedder):
    assert store.load(loaded, PAGES, fake_embedder) == 3
    assert sorted(store.stored(loaded)) == ["bags#1", "bags#2", "food#1"]


def test_vectors_come_back_as_vectors_not_text(loaded):
    # Without pgvector's types registered, the driver hands vectors back as strings like
    # "[0.12,-0.03,...]" (Morning Manna's Card 8.1 lesson).
    (vector,) = loaded.execute("select embedding from passages limit 1").fetchone()
    assert not isinstance(vector, str)
    assert vector.to_numpy().shape == (384,)


def test_meaning_finds_the_closest_passage(loaded, fake_embedder):
    assert by_meaning(loaded, fake_embedder.question("jollof rice"))[0] == "food#1"


def test_keyword_matches_any_word_and_ranks_the_best_first(loaded):
    assert by_keyword(loaded, "jollof dumplings")[0] == "food#1"
    assert by_keyword(loaded, "the of and") == []


def test_keyword_search_reads_the_title_too(loaded):
    # "baggage" appears only in the page title, which travels with each of its passages.
    assert set(by_keyword(loaded, "baggage")) == {"bags#1", "bags#2"}


def test_each_method_returns_a_ranking(loaded, fake_embedder):
    for method in ("meaning", "keyword", "hybrid"):
        assert search(loaded, fake_embedder, "cabin bag", method)


def test_an_unknown_method_is_refused(loaded, fake_embedder):
    with pytest.raises(ValueError, match="method must be one of"):
        search(loaded, fake_embedder, "cabin bag", "magic")


def test_an_empty_store_reports_nothing(db):
    assert store.stored(db) == {}
