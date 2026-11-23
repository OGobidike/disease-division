"""The librarian: answers a customer's question from the passages search finds, and cites them.

Each passage goes to Claude as a search result, cut into sentences, with citations switched on.
When Claude cites, the reply carries the exact sentences it cited and the passage they came from,
so code can check each citation instead of trusting it. Citing is Claude's choice: a reply may
cite nothing, and the report counts how often that happens.

Everything that shapes an answer is fixed here, before any golden question is answered: the
model, the effort, the instructions, the refusal sentence, how search finds the passages, how many
the librarian reads and how they are cut and titled. Each reply records a fingerprint of all of them
(`settings`), and a run refuses to mix replies made under different settings, so a change after
seeing results can only ever start a new run, never quietly join an old one.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Protocol

from disease_division import embed, search
from disease_division.kb import Passage

DEFAULT_MODEL = "claude-haiku-5-5"
MODELS = ("claude-haiku-5-5", "claude-opus-5-5")

# US dollars per million tokens: Anthropic's list prices for prompts under 100,000 tokens, as
# published on 2026-11-23. Costs are these prices times the token counts the API itself reports.
PRICES = {
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-opus-5-5": (4.00, 20.00),
}
# Prompt caching is never requested. If the API ever reports cached tokens anyway, they are
# priced at the plain input price, which is not their real price (a cache write costs more, a
# read less), so the report says the cost is approximate whenever that happens.

EFFORT = "medium"  # the default on both models, written out so it can't drift
MAX_TOKENS = 4096  # thinking and the reply share this; a short answer needs a fraction of it
# The librarian reads the first five results: the first screen the first score measured.
PASSAGES = 5
METHOD = "hybrid"  # meaning and keywords fused, as the blueprint fixed before any search ran

REFUSAL = "I can't find that in Zuma Air's help pages."

SYSTEM = f"""You are the help desk assistant for Zuma Air, an airline based in Abuja, Nigeria. \
Customers write to you with questions.

Each question comes with search results from Zuma Air's help pages. Answer only from those \
search results. Never answer from general knowledge.

If the search results don't answer the question, reply with exactly this sentence: "{REFUSAL}" \
After it you may add one short sentence saying what the help pages do cover nearby.

If the question can be answered yes or no, begin your reply with Yes or No.

Keep replies short: two or three sentences in plain words."""

# The closed-book run asks the same questions with no pages at all, to show how much a model
# can answer from what it already knows about airlines in general.
CLOSED_BOOK_SYSTEM = """You are the help desk assistant for Zuma Air, an airline based in \
Abuja, Nigeria. Customers write to you with questions.

You have no help pages to hand. Answer as well as you can from what you know about how airlines \
usually work, and give your best single answer, with numbers where the question asks for them. \
If the question can be answered yes or no, begin your reply with Yes or No.

Keep replies short: two or three sentences in plain words."""

# Sentences end at . ! or ? followed by a space and a capital or a digit, except after "no."
# (as in "Control no. ZA-DC-4182"), "e.g." and "i.e.".
_SENTENCE_END = re.compile(
    r"(?<=[.!?])(?<!\b[Nn]o\.)(?<!\be\.g\.)(?<!\bi\.e\.)\s+(?=[\"(]?[A-Z0-9])"
)


def sentences(text: str) -> list[str]:
    """Cut a passage into sentences. A citation covers whole sentences, so this sets how
    finely Claude can cite: one sentence is the smallest thing it can point at."""
    out = []
    for paragraph in re.split(r"\n\s*\n", text.strip()):
        paragraph = " ".join(paragraph.split())
        out += [s for s in _SENTENCE_END.split(paragraph) if s]
    return out


def settings(model: str, closed_book: bool = False) -> dict:
    """Everything that shapes a reply, so a run can tell whether two replies are comparable."""
    return {
        "model": model,
        "effort": EFFORT,
        "max_tokens": MAX_TOKENS,
        "closed_book": closed_book,
        "method": None if closed_book else METHOD,
        "passages": 0 if closed_book else PASSAGES,
        "system": CLOSED_BOOK_SYSTEM if closed_book else SYSTEM,
        "sentences": _SENTENCE_END.pattern,
        "title": TITLE,
        # How search finds the passages, since that shapes what the librarian reads.
        "search": None
        if closed_book
        else {
            "embedding": embed.MODEL,
            "question_prefix": embed.QUESTION_PREFIX,
            "pool": search.POOL,
            "rrf_k": search.RRF_K,
        },
    }


def fingerprint(model: str, closed_book: bool = False) -> str:
    """A short checksum of `settings`, stored with every reply."""
    text = json.dumps(settings(model, closed_book), sort_keys=True)
    return hashlib.md5(text.encode()).hexdigest()[:12]


TITLE = "{title} / {heading}"  # how a passage is titled when it has a section heading


def heading_of(passage: Passage) -> str:
    return (
        TITLE.format(title=passage.title, heading=passage.heading)
        if passage.heading
        else passage.title
    )


def search_results(passages: list[Passage]) -> list[dict]:
    """The passages as search result blocks, one text block per sentence, citations on."""
    return [
        {
            "type": "search_result",
            "source": p.id,
            "title": heading_of(p),
            "content": [{"type": "text", "text": s} for s in sentences(p.text)],
            "citations": {"enabled": True},
        }
        for p in passages
    ]


def build_request(
    question: str, passages: list[Passage], model: str = DEFAULT_MODEL, closed_book: bool = False
) -> dict:
    """Everything sent to the Messages API for one question. The search results come first and
    the question last, the order Anthropic recommends for long material."""
    if model not in PRICES:
        raise ValueError(f"model must be one of {MODELS}, not {model!r}")
    if closed_book:
        system, content = CLOSED_BOOK_SYSTEM, [{"type": "text", "text": question}]
    else:
        system = SYSTEM
        content = [*search_results(passages), {"type": "text", "text": question}]
    return {
        "model": model,
        "max_tokens": MAX_TOKENS,
        "system": system,
        "output_config": {"effort": EFFORT},
        "messages": [{"role": "user", "content": content}],
    }


@dataclass(frozen=True)
class Citation:
    passage: str  # the passage id the cited text came from (the search result's source)
    result: int  # which search result, counting from 0 in the order they were sent
    start: int  # the first cited sentence of that result, counting from 0
    end: int  # one past the last cited sentence
    text: str  # the cited sentences, as the API returned them


@dataclass(frozen=True)
class Reply:
    text: str
    citations: tuple[Citation, ...]
    stop_reason: str
    model: str
    input_tokens: int
    output_tokens: int
    cache_write_tokens: int = 0
    cache_read_tokens: int = 0
    request_id: str = ""

    @property
    def cost(self) -> float:
        """US dollars, from the API's own token counts at the list prices above."""
        price_in, price_out = PRICES[self.model]
        return (
            (self.input_tokens + self.cache_write_tokens + self.cache_read_tokens) * price_in
            + self.output_tokens * price_out
        ) / 1_000_000


def read_message(message, model: str) -> Reply:
    """Turn the API's Message into a Reply. Thinking blocks are skipped; the reply's text is
    every text block joined, because the API splits text wherever a citation starts or ends."""
    text, citations = [], []
    for block in message.content:
        if block.type != "text":
            continue
        text.append(block.text)
        for c in block.citations or ():
            if c.type == "search_result_location":
                citations.append(
                    Citation(
                        c.source,
                        c.search_result_index,
                        c.start_block_index,
                        c.end_block_index,
                        c.cited_text,
                    )
                )
    usage = message.usage
    return Reply(
        text="".join(text).strip(),
        citations=tuple(citations),
        stop_reason=message.stop_reason or "",
        model=model,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cache_write_tokens=usage.cache_creation_input_tokens or 0,
        cache_read_tokens=usage.cache_read_input_tokens or 0,
        request_id=getattr(message, "_request_id", "") or "",
    )


class Model(Protocol):
    name: str

    def answer(
        self, question: str, passages: list[Passage], closed_book: bool = False
    ) -> Reply: ...


class Claude:
    """The real model. The client is built on first use, so nothing touches the network or
    needs a key until a question is actually asked."""

    def __init__(self, name: str = DEFAULT_MODEL, client=None) -> None:
        if name not in PRICES:
            raise ValueError(f"model must be one of {MODELS}, not {name!r}")
        self.name = name
        self._client = client

    @property
    def client(self):
        if self._client is None:
            import anthropic

            # The SDK retries rate limits, overloads and dropped connections with backoff.
            self._client = anthropic.Anthropic(max_retries=4)
        return self._client

    def answer(self, question: str, passages: list[Passage], closed_book: bool = False) -> Reply:
        request = build_request(question, passages, self.name, closed_book)
        return read_message(self.client.messages.create(**request), self.name)
