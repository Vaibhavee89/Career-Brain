from collections.abc import Sequence

import pytest
from fastapi.testclient import TestClient

from careerbrain.adapters.http_api import build_app
from careerbrain.core.engine import Engine
from careerbrain.core.llm import LLMError
from careerbrain.core.memory import Message
from careerbrain.core.ratelimit import CooldownLimiter
from careerbrain.core.types import Page, SearchResult


class FakeRetriever:
    def search(self, query: str, limit: int = 5) -> list[SearchResult]:
        page = Page(path="projects/etl.md", frontmatter={"public": "true"}, body="etl")
        return [SearchResult(page=page, score=1, snippet="etl")]


class FakeLLM:
    def __init__(self, replies: Sequence[str | Exception]) -> None:
        self._replies = list(replies)
        self.calls: list[list[Message]] = []

    def complete(self, messages: Sequence[Message]) -> str:
        self.calls.append(list(messages))
        item = self._replies.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def _client(
    llm: FakeLLM, clock: FakeClock | None = None
) -> tuple[TestClient, FakeClock]:
    clock = clock or FakeClock()
    engine = Engine(
        retriever=FakeRetriever(),
        llm=llm,
        limiter=CooldownLimiter(10.0, clock=clock),
    )
    return TestClient(build_app(engine)), clock


def test_healthz_reports_ok() -> None:
    client, _ = _client(FakeLLM([]))
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ask_returns_reply_chunks_and_sources() -> None:
    client, _ = _client(FakeLLM(["an answer"]))
    response = client.post("/ask", json={"user_id": "alice", "message": "hi"})
    assert response.status_code == 200
    assert response.json() == {
        "kind": "reply",
        "chunks": ["an answer"],
        "sources": ["projects/etl.md"],
    }


def test_ask_rate_limit_returns_429_with_retry_after() -> None:
    client, clock = _client(FakeLLM(["first", "second"]))
    client.post("/ask", json={"user_id": "alice", "message": "one"})
    clock.now = 4.0
    response = client.post("/ask", json={"user_id": "alice", "message": "two"})
    assert response.status_code == 429
    assert response.headers["Retry-After"] == "6"
    assert response.json()["kind"] == "rate_limited"


def test_reset_clears_history() -> None:
    llm = FakeLLM(["first", "second"])
    client, clock = _client(llm)
    client.post("/ask", json={"user_id": "alice", "message": "one"})

    response = client.post("/reset", json={"user_id": "alice"})
    assert response.status_code == 200
    assert response.json() == {"kind": "reset"}

    clock.now = 10.0
    client.post("/ask", json={"user_id": "alice", "message": "two"})
    assert [m.content for m in llm.calls[1][1:]] == ["two"]


@pytest.mark.parametrize(
    "body",
    [
        {"user_id": "alice", "message": ""},
        {"user_id": "", "message": "hi"},
        {"message": "hi"},
        {"user_id": "alice", "message": "x" * 2001},
        {"user_id": "u" * 129, "message": "hi"},
    ],
)
def test_ask_rejects_invalid_bodies(body: dict) -> None:
    client, _ = _client(FakeLLM([]))
    assert client.post("/ask", json=body).status_code == 422


def test_ask_maps_llm_failure_to_502_without_leaking_details() -> None:
    client, _ = _client(FakeLLM([LLMError("secret upstream detail")]))
    response = client.post("/ask", json={"user_id": "alice", "message": "hi"})
    assert response.status_code == 502
    assert response.json() == {"detail": "language model unavailable"}
    assert "secret" not in response.text


def test_reset_rejects_missing_user_id() -> None:
    client, _ = _client(FakeLLM([]))
    assert client.post("/reset", json={}).status_code == 422
