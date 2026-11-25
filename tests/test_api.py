"""The API, with a stand-in model and search, so no test spends money or needs a key."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from disease_division.api import (
    MAX_BODY,
    MAX_QUESTION,
    STAFF,
    Spending,
    build,
    create_app,
    worst_case,
)
from disease_division.kb import all_passages, load_documents
from disease_division.librarian import REFUSAL, Citation, Reply, fingerprint, sentences

ROOT = Path(__file__).resolve().parents[1]
DOCUMENTS = load_documents(ROOT / "kb")
PASSAGES = {p.id: p for p in all_passages(DOCUMENTS)}
FEES, GOODWILL = PASSAGES["changing-a-flight#2"], PASSAGES["staff-goodwill#3"]
PER_CALL = (1_000 * 0.10 + 100 * 0.50) / 1_000_000
HOLD = worst_case("claude-haiku-5-5")


class Quoting:
    """Quotes and cites the first sentence of the first passage it is given, or declines."""

    name = "claude-haiku-5-5"

    def answer(self, question, passages, closed_book=False):
        if not passages:
            return Reply(REFUSAL, (), "end_turn", self.name, 1_000, 100)
        first = sentences(passages[0].text)[0]
        cited = (Citation(passages[0].id, 0, 0, 1, first),)
        return Reply(first, cited, "end_turn", self.name, 1_000, 100)


def client(model=None, retrieve=None, store_ok=lambda: True, budget=1.0):
    def search(question):
        return [FEES, GOODWILL]

    app = create_app(model or Quoting(), retrieve or search, DOCUMENTS, store_ok, budget)
    return TestClient(app, base_url="http://127.0.0.1")


def test_health_says_the_store_matches_and_names_the_settings():
    body = client().get("/health").json()
    assert body["status"] == "ok"
    assert body["settings"] == fingerprint("claude-haiku-5-5")
    assert body["spent_usd"] == 0


def test_health_fails_plainly_when_the_store_is_stale_or_unreachable():
    stale = client(store_ok=lambda: False).get("/health")
    assert stale.status_code == 503 and "division load" in stale.json()["detail"]

    def down():
        raise OSError("no database")

    gone = client(store_ok=down).get("/health")
    assert gone.status_code == 503 and "can't be reached" in gone.json()["detail"]


def test_an_answer_comes_with_its_citations_passages_and_cost():
    response = client().post("/ask", json={"question": "How much is a change on Savanna?"})
    assert response.status_code == 200
    body = response.json()
    assert body["answer"].startswith("A change on a Savanna fare costs NGN 9,000")
    assert body["declined"] is False
    assert body["citations"] == [{"passage": FEES.id, "text": body["answer"]}]
    assert [p["id"] for p in body["passages"]] == [FEES.id, STAFF]
    assert body["passages"][1] == {
        "id": STAFF,
        "title": STAFF,
        "source": "staff",
        "visibility": "staff",
    }
    assert body["cost_usd"] == pytest.approx(PER_CALL)
    assert body["spent_usd"] == pytest.approx(PER_CALL)
    assert body["settings"] == fingerprint("claude-haiku-5-5")


def test_a_passage_is_never_returned_as_text_so_staff_pages_stay_out_of_the_response():
    response = client().post("/ask", json={"question": "Any goodwill?"})
    assert "20,000" not in response.text
    assert all(
        set(p) == {"id", "title", "source", "visibility"} for p in response.json()["passages"]
    )


def test_a_question_search_finds_nothing_for_is_declined():
    body = client(retrieve=lambda q: []).post("/ask", json={"question": "Wi-Fi?"}).json()
    assert body["declined"] is True and body["passages"] == [] and body["citations"] == []


@pytest.mark.parametrize("question", ["", "   ", "x" * (MAX_QUESTION + 1)])
def test_an_empty_or_overlong_question_is_refused_before_anything_is_spent(question):
    asked = []

    def search(q):
        asked.append(q)
        return [FEES]

    response = client(retrieve=search).post("/ask", json={"question": question})
    assert response.status_code == 422 and asked == []


def test_the_server_never_starts_a_call_its_worst_case_could_take_past_the_budget():
    api = client(budget=HOLD + 2.5 * PER_CALL)
    for question in ("a?", "b?", "c?"):
        assert api.post("/ask", json={"question": question}).status_code == 200
    refused = api.post("/ask", json={"question": "d?"})
    assert refused.status_code == 429 and "budget" in refused.json()["detail"]
    assert api.get("/health").json()["spent_usd"] == pytest.approx(3 * PER_CALL)


def test_answers_given_at_the_same_time_cannot_add_up_past_the_budget():
    import threading

    spending = Spending(budget=1.5 * HOLD)
    start = threading.Barrier(20)
    granted = []

    def ask():
        start.wait()
        granted.append(spending.reserve(HOLD))

    threads = [threading.Thread(target=ask) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert granted.count(True) == 1


def test_a_model_error_is_a_short_502_with_nothing_sensitive_in_it():
    import anthropic
    import httpx2

    class Failing(Quoting):
        def answer(self, question, passages, closed_book=False):
            request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
            raise anthropic.RateLimitError(
                "slow down", response=httpx2.Response(429, request=request), body=None
            )

    api = client(model=Failing())
    response = api.post("/ask", json={"question": "a?"})
    assert response.status_code == 502
    assert response.json()["detail"] == "the model's API failed (RateLimitError, 429)"
    # It may have been billed, so its worst case stays counted.
    assert api.get("/health").json()["spent_usd"] == pytest.approx(HOLD, abs=1e-6)


def test_the_real_wiring_searches_the_store_for_each_question(db, fake_embedder):
    from psycopg.conninfo import make_conninfo

    from disease_division import store

    store.load(db, DOCUMENTS, fake_embedder)
    url = make_conninfo(store.url(), dbname=db.info.dbname)
    api = TestClient(
        build(DOCUMENTS, fake_embedder, Quoting(), 1.0, url=url), base_url="http://127.0.0.1"
    )
    assert api.get("/health").status_code == 200
    body = api.post("/ask", json={"question": "How much does it cost to change a flight?"}).json()
    assert len(body["passages"]) == 5 and body["citations"]
    store.load(db, DOCUMENTS[:3], fake_embedder)
    assert api.get("/health").status_code == 503


class CitingStaff(Quoting):
    def answer(self, question, passages, closed_book=False):
        text = sentences(GOODWILL.text)[0]
        return Reply(
            "I can't say.", (Citation(GOODWILL.id, 1, 0, 1, text),), "end_turn", self.name, 1, 1
        )


def test_a_citation_of_a_staff_page_comes_back_without_its_text_or_its_name():
    response = client(model=CitingStaff()).post("/ask", json={"question": "Goodwill limits?"})
    body = response.json()
    assert body["citations"] == [{"passage": STAFF, "text": None}]
    assert "20,000" not in response.text and "goodwill" not in response.text.lower()


@pytest.mark.parametrize("host", ["evil.example", "192.168.1.10", "rebound.attacker.test"])
def test_a_request_addressed_to_any_other_name_is_refused(host):
    response = client().post("/ask", json={"question": "a?"}, headers={"host": host})
    assert response.status_code == 400


def test_an_oversized_body_is_refused_before_it_is_read():
    response = client().post(
        "/ask",
        content=b'{"question": "' + b"x" * MAX_BODY + b'"}',
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 413


@pytest.mark.parametrize("budget", [float("nan"), float("inf"), 0.0, -1.0])
def test_a_budget_that_is_not_a_positive_number_is_refused(budget):
    with pytest.raises(ValueError, match="positive number"):
        Spending(budget)


def test_the_servers_model_makes_no_automatic_retries(monkeypatch):
    from disease_division.librarian import Claude

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-not-a-key")
    assert Claude(max_retries=0).client.max_retries == 0
    assert Claude().client.max_retries == 4
