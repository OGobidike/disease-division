"""The librarian: how passages go to Claude, and how its reply comes back. No call is ever made:
the client is a stand-in that returns a real SDK Message."""

from pathlib import Path

import pytest
from anthropic.types import Message

from disease_division.kb import Passage, all_passages, load_documents
from disease_division.librarian import (
    CLOSED_BOOK_SYSTEM,
    EFFORT,
    REFUSAL,
    SYSTEM,
    Claude,
    build_request,
    read_message,
    search_results,
    sentences,
)

ROOT = Path(__file__).resolve().parents[1]

FEES = Passage(
    "changing-a-flight#2",
    "changing-a-flight",
    "Changing a flight",
    "Fees",
    "A change on a Savanna fare costs NGN 9,000 per passenger per flight.\n"
    "A change on a Plateau fare costs NGN 5,000.\n\nPeak changes are free.",
)


def test_sentences_end_at_full_stops_but_not_inside_a_control_number():
    assert sentences("Internal only. Do not share.\n\nControl no. ZA-DC-4182") == [
        "Internal only.",
        "Do not share.",
        "Control no. ZA-DC-4182",
    ]


def test_every_real_passage_cuts_into_sentences_that_rebuild_it():
    for p in all_passages(load_documents(ROOT / "kb")):
        parts = sentences(p.text)
        assert parts and all(parts)
        assert "".join(parts).replace(" ", "") == "".join(p.text.split())


def test_passages_go_as_search_results_one_sentence_per_block_with_citations_on():
    (result,) = search_results([FEES])
    assert result["type"] == "search_result"
    assert result["source"] == "changing-a-flight#2"
    assert result["title"] == "Changing a flight / Fees"
    assert result["citations"] == {"enabled": True}
    assert [b["text"] for b in result["content"]] == sentences(FEES.text)
    assert len(result["content"]) == 3


def test_the_request_puts_the_passages_first_and_the_question_last():
    request = build_request("How much is a change?", [FEES])
    assert request["model"] == "claude-haiku-5-5"
    assert request["system"] == SYSTEM
    assert REFUSAL in SYSTEM
    assert request["output_config"] == {"effort": EFFORT}
    (message,) = request["messages"]
    assert message["role"] == "user"
    assert [b["type"] for b in message["content"]] == ["search_result", "text"]
    assert message["content"][-1]["text"] == "How much is a change?"


def test_the_request_sends_no_sampling_settings_the_current_api_refuses():
    request = build_request("?", [FEES])
    assert not {"temperature", "top_p", "top_k", "thinking"} & request.keys()


def test_closed_book_sends_the_question_alone_under_its_own_instructions():
    request = build_request("How much is a change?", [FEES], closed_book=True)
    assert request["system"] == CLOSED_BOOK_SYSTEM
    assert request["messages"][0]["content"] == [{"type": "text", "text": "How much is a change?"}]


def test_only_the_two_priced_models_are_allowed():
    with pytest.raises(ValueError, match="model must be one of"):
        build_request("?", [FEES], model="claude-something-else")


def message(content, stop_reason="end_turn", usage=None):
    return Message.model_validate(
        {
            "id": "msg_test",
            "type": "message",
            "role": "assistant",
            "model": "claude-haiku-5-5",
            "content": content,
            "stop_reason": stop_reason,
            "stop_sequence": None,
            "usage": usage or {"input_tokens": 1_000, "output_tokens": 200},
        }
    )


FEES_FIRST = "A change on a Savanna fare costs NGN 9,000 per passenger per flight."
CITED = [
    {"type": "thinking", "thinking": "", "signature": "x"},
    {"type": "text", "text": "It costs ", "citations": None},
    {
        "type": "text",
        "text": "NGN 9,000 per passenger.",
        "citations": [
            {
                "type": "search_result_location",
                "source": "changing-a-flight#2",
                "title": "Changing a flight / Fees",
                "cited_text": FEES_FIRST,
                "search_result_index": 0,
                "start_block_index": 0,
                "end_block_index": 1,
            }
        ],
    },
]


def test_a_reply_joins_its_text_skips_thinking_and_keeps_every_citation():
    reply = read_message(message(CITED), "claude-haiku-5-5")
    assert reply.text == "It costs NGN 9,000 per passenger."
    (c,) = reply.citations
    assert (c.passage, c.result, c.start, c.end) == ("changing-a-flight#2", 0, 0, 1)
    assert c.text.startswith("A change on a Savanna fare")
    assert reply.stop_reason == "end_turn"


def test_the_cost_comes_from_the_api_token_counts_at_list_prices():
    reply = read_message(message(CITED), "claude-haiku-5-5")
    assert reply.cost == pytest.approx((1_000 * 0.10 + 200 * 0.50) / 1_000_000)
    opus = read_message(message(CITED), "claude-opus-5-5")
    assert opus.cost == pytest.approx((1_000 * 4 + 200 * 20) / 1_000_000)


def test_cached_tokens_are_priced_at_the_full_input_price_so_cost_is_never_hidden():
    usage = {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_creation_input_tokens": 1_000_000,
        "cache_read_input_tokens": 1_000_000,
    }
    reply = read_message(message(CITED, usage=usage), "claude-haiku-5-5")
    assert reply.cost == pytest.approx(0.20)


def test_the_settings_fingerprint_changes_with_anything_that_shapes_a_reply(monkeypatch):
    from disease_division import librarian

    base = librarian.fingerprint("claude-haiku-5-5")
    assert base == librarian.fingerprint("claude-haiku-5-5")
    assert base != librarian.fingerprint("claude-opus-5-5")
    assert base != librarian.fingerprint("claude-haiku-5-5", closed_book=True)
    monkeypatch.setattr(librarian, "SYSTEM", librarian.SYSTEM + " Be brief.")
    assert base != librarian.fingerprint("claude-haiku-5-5")


def test_the_fingerprint_covers_how_search_finds_the_passages(monkeypatch):
    from disease_division import librarian, search

    base = librarian.fingerprint("claude-haiku-5-5")
    monkeypatch.setattr(search, "RRF_K", 61)
    assert base != librarian.fingerprint("claude-haiku-5-5")


def test_a_declined_request_comes_back_empty_with_its_stop_reason():
    reply = read_message(message([], stop_reason="refusal"), "claude-haiku-5-5")
    assert reply.text == "" and reply.citations == () and reply.stop_reason == "refusal"


class FakeClient:
    """Stands in for anthropic.Anthropic: records each request and answers with a Message."""

    def __init__(self, reply):
        self.requests = []
        self.messages = self
        self._reply = reply

    def create(self, **request):
        self.requests.append(request)
        return self._reply


def test_claude_sends_the_built_request_and_reads_the_reply():
    client = FakeClient(message(CITED))
    reply = Claude("claude-haiku-5-5", client=client).answer("How much is a change?", [FEES])
    assert client.requests == [build_request("How much is a change?", [FEES])]
    assert reply.text == "It costs NGN 9,000 per passenger."


def test_claude_needs_no_key_until_a_question_is_asked(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert Claude().name == "claude-haiku-5-5"
