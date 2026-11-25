"""The API: one endpoint that answers a customer's question the librarian's way.

`POST /ask` takes a question and returns the librarian's answer, whether it declined, the sentences
it cited, the passages it read, the tokens, the cost, and the fingerprint of the settings that made
it. It is the same librarian the golden run scored (the same model, instructions and search), so
what the API says is what the scores measure. `GET /health` says whether the store matches the
pages, and costs nothing.

The API itself never shows a staff-only page: a staff passage the librarian read, or cited, comes
back only as "(staff only)", with no id, title or text. So whatever staff-only content reaches
the asker gets there through the librarian's own reply, which is exactly what the scores measure
(and what Phase 4's defenses will try to stop).

Every answer spends money, so the server guards itself:

- It answers only to requests addressed to 127.0.0.1 or localhost, so a web page can't reach it
  through a renamed address (DNS rebinding), and it takes no body over 16 KB.
- Before each call it reserves the most that call could cost, and it never starts a call whose
  reservation would take it past its budget (default $1.00 a run). After the call it settles
  the real cost. A call that fails after starting keeps its reservation counted, since the API may
  have billed it. Requests answered at the same time can't add up past the budget. The server's
  client makes no automatic retries, so one request is at most one billed call.
- It refuses questions longer than 500 characters.

Set a spend limit in the Claude Console as well: that is the limit no bug here can get past.
"""

from __future__ import annotations

import math
import threading
from collections.abc import Callable

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from disease_division.grade import refuses
from disease_division.kb import Document, Passage
from disease_division.librarian import MAX_TOKENS, PRICES, Model, fingerprint, heading_of

MAX_QUESTION = 500  # characters
MAX_BODY = 16_384  # bytes
MAX_INPUT_TOKENS = 20_000  # far above a real call (about 2,000): five passages and a short question
DEFAULT_BUDGET = 1.00  # US dollars per server run
HOSTS = ("127.0.0.1", "localhost")
STAFF = "(staff only)"


def worst_case(model: str) -> float:
    """The most one call could cost: the input ceiling above and a full reply, at list prices."""
    price_in, price_out = PRICES[model]
    return (MAX_INPUT_TOKENS * price_in + MAX_TOKENS * price_out) / 1_000_000


class Ask(BaseModel):
    question: str = Field(min_length=1, max_length=MAX_QUESTION)


class Cited(BaseModel):
    passage: str  # the passage id, or "(staff only)"
    text: str | None  # the cited sentences; None when they come from a staff-only page


class Read(BaseModel):
    id: str  # the passage id, or "(staff only)"
    title: str
    source: str  # staff, web or email
    visibility: str  # public or staff


class Answer(BaseModel):
    answer: str
    declined: bool
    citations: list[Cited]
    passages: list[Read]
    model: str
    settings: str
    stop_reason: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    spent_usd: float  # this server's spending so far, this answer included
    budget_usd: float


class Spending:
    """The server's money, shared safely between requests answered at the same time."""

    def __init__(self, budget: float) -> None:
        if not math.isfinite(budget) or budget <= 0:
            raise ValueError(f"a budget is a positive number of US dollars, not {budget!r}")
        self.budget = budget
        self.spent = 0.0
        self.reserved = 0.0
        self._lock = threading.Lock()

    def reserve(self, amount: float) -> bool:
        """Set aside `amount` for a call, unless that would take the server past its budget."""
        with self._lock:
            if self.spent + self.reserved + amount > self.budget:
                return False
            self.reserved += amount
            return True

    def settle(self, reserved: float, cost: float) -> float:
        """Release a reservation and count what the call really cost. Returns the new total."""
        with self._lock:
            self.reserved -= reserved
            self.spent += cost
            return self.spent


def create_app(
    model: Model,
    retrieve: Callable[[str], list[Passage]],
    documents: list[Document],
    store_ok: Callable[[], bool],
    budget: float = DEFAULT_BUDGET,
    hosts: tuple[str, ...] = HOSTS,
) -> FastAPI:
    """The app, with its parts passed in: the model, the search, the pages and a store check.
    `build` wires the real ones; the tests pass stand-ins, so they never spend money."""
    import anthropic

    pages = {d.id: d for d in documents}
    spending = Spending(budget)
    app = FastAPI(
        title="The Disease Division: the librarian",
        description="Zuma Air's help desk assistant. Answers from the help pages, with citations.",
    )
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(hosts))

    @app.middleware("http")
    async def limit_body(request: Request, call_next):
        if request.method == "POST":
            length = request.headers.get("content-length")
            if length is None:
                return JSONResponse({"detail": "send the body with a Content-Length"}, 411)
            if not length.isdigit() or int(length) > MAX_BODY:
                return JSONResponse({"detail": f"the body is over {MAX_BODY} bytes"}, 413)
        return await call_next(request)

    def public(passage_id: str) -> bool:
        return pages[passage_id.split("#", 1)[0]].visibility == "public"

    @app.get("/health")
    def health() -> dict:
        try:
            ok = store_ok()
        except Exception as error:  # the database is down or unreachable
            raise HTTPException(503, f"the store can't be reached ({error.__class__.__name__})")
        if not ok:
            raise HTTPException(503, "the store doesn't match the pages: run `division load`")
        return {
            "status": "ok",
            "model": model.name,
            "settings": fingerprint(model.name),
            "spent_usd": round(spending.spent, 6),
            "budget_usd": budget,
        }

    @app.post("/ask", response_model=Answer)
    def ask(body: Ask) -> Answer:
        question = body.question.strip()
        if not question:
            raise HTTPException(422, "the question is empty")
        hold = worst_case(model.name)
        if not spending.reserve(hold):
            raise HTTPException(
                429,
                f"this server's ${budget:g} budget is spent, or held by answers still in progress:"
                " try again in a moment, or restart the server for a new budget",
            )
        try:
            passages = retrieve(question)
        except Exception:
            spending.settle(hold, 0.0)  # nothing was sent to the model
            raise
        try:
            reply = model.answer(question, passages)
        except anthropic.APIError as error:
            spending.settle(hold, hold)  # it may have been billed: keep the reservation counted
            status = getattr(error, "status_code", None)
            what = error.__class__.__name__ + (f", {status}" if status else "")
            raise HTTPException(502, f"the model's API failed ({what})")
        except Exception:
            spending.settle(hold, hold)
            raise
        spent = spending.settle(hold, reply.cost)
        return Answer(
            answer=reply.text,
            declined=refuses(reply.text),
            citations=[
                Cited(passage=c.passage, text=c.text)
                if public(c.passage)
                else Cited(passage=STAFF, text=None)
                for c in reply.citations
            ],
            passages=[
                Read(
                    id=p.id if public(p.id) else STAFF,
                    title=heading_of(p) if public(p.id) else STAFF,
                    source=pages[p.doc_id].source,
                    visibility=pages[p.doc_id].visibility,
                )
                for p in passages
            ],
            model=reply.model,
            settings=fingerprint(reply.model),
            stop_reason=reply.stop_reason,
            input_tokens=reply.input_tokens,
            output_tokens=reply.output_tokens,
            cost_usd=round(reply.cost, 8),
            spent_usd=round(spent, 6),
            budget_usd=budget,
        )

    return app


def build(documents: list[Document], embedder, model: Model, budget: float, url: str | None = None):
    """The real app: each request opens its own connection to the store, searches it the
    librarian's way, and asks the model."""
    from disease_division import store
    from disease_division.kb import all_passages
    from disease_division.librarian import METHOD, PASSAGES
    from disease_division.search import search

    by_id = {p.id: p for p in all_passages(documents)}

    def retrieve(question: str) -> list[Passage]:
        with store.connect(url) as conn:
            return [by_id[i] for i in search(conn, embedder, question, METHOD)[:PASSAGES]]

    def store_ok() -> bool:
        with store.connect(url, connect_timeout=3) as conn:
            return store.matches(conn, documents, embedder.model)

    return create_app(model, retrieve, documents, store_ok, budget)
