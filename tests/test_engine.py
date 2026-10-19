from collections.abc import Sequence

import pytest

from careerbrain.core.engine import Engine
from careerbrain.core.llm import LLMError
from careerbrain.core.memory import Message
from careerbrain.core.ratelimit import CooldownLimiter
from careerbrain.core.types import Page, SearchResult


class FakeRetriever:
    def __init__(self, results: list[SearchResult] | None = None) -> None:
        self.results = results or []
        self.queries: list[str] = []

    def search(self, query: str, limit: int = 5) -> list[SearchResult]:
        self.queries.append(query)
        return self.results[:limit]


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


def _page(
    path: str, body: str, frontmatter: dict[str, str] | None = None
) -> SearchResult:
    fm = {"public": "true", **(frontmatter or {})}
    page = Page(path=path, frontmatter=fm, body=body)
    return SearchResult(page=page, score=1, snippet=body)


def _engine(
    llm: FakeLLM,
    retriever: FakeRetriever | None = None,
    clock: FakeClock | None = None,
    cooldown: float = 10.0,
    memory_max_tokens: int = 2000,
    site_base_url: str | None = None,
) -> tuple[Engine, FakeRetriever, FakeClock]:
    retriever = retriever or FakeRetriever(
        [_page("projects/etl.md", "built an ETL agent")]
    )
    clock = clock or FakeClock()
    engine = Engine(
        retriever=retriever,
        llm=llm,
        limiter=CooldownLimiter(cooldown, clock=clock),
        memory_max_tokens=memory_max_tokens,
        site_base_url=site_base_url,
    )
    return engine, retriever, clock


def test_reply_flow_retrieves_context_and_calls_llm() -> None:
    llm = FakeLLM(["It was an ETL agent."])
    engine, retriever, _ = _engine(llm)

    result = engine.handle("alice", "what did you build?", message_limit=2000)

    assert result.kind == "reply"
    assert result.chunks == ["It was an ETL agent."]
    assert result.sources == ["projects/etl.md"]
    assert retriever.queries == ["what did you build?"]

    system, user = llm.calls[0]
    assert system.role == "system"
    assert "built an ETL agent" in system.content
    assert "projects/etl.md" in system.content
    assert user == Message("user", "what did you build?")


def test_no_hits_tells_the_model_nothing_matched() -> None:
    llm = FakeLLM(["I don't know."])
    engine, _, _ = _engine(llm, retriever=FakeRetriever([]))

    result = engine.handle("alice", "anything", message_limit=2000)

    assert result.sources == []
    assert "No matching pages" in llm.calls[0][0].content


def test_history_is_carried_into_next_call() -> None:
    llm = FakeLLM(["first answer", "second answer"])
    engine, _, clock = _engine(llm, cooldown=1.0)

    engine.handle("alice", "question one", message_limit=2000)
    clock.now = 5.0
    engine.handle("alice", "question two", message_limit=2000)

    roles = [(m.role, m.content) for m in llm.calls[1][1:]]
    assert roles == [
        ("user", "question one"),
        ("assistant", "first answer"),
        ("user", "question two"),
    ]


def test_reply_is_split_to_adapter_limit() -> None:
    llm = FakeLLM(["alpha beta gamma delta"])
    engine, _, _ = _engine(llm)

    result = engine.handle("alice", "hi", message_limit=11)

    assert result.chunks == ["alpha beta", "gamma delta"]
    assert all(len(chunk) <= 11 for chunk in result.chunks)


def test_reset_command_clears_history_without_calling_llm() -> None:
    llm = FakeLLM(["first answer", "after reset"])
    engine, _, clock = _engine(llm, cooldown=1.0)

    engine.handle("alice", "question one", message_limit=2000)
    clock.now = 5.0
    reset = engine.handle("alice", "/reset", message_limit=2000)
    clock.now = 10.0
    engine.handle("alice", "question two", message_limit=2000)

    assert reset.kind == "reset"
    assert len(llm.calls) == 2
    assert [m.content for m in llm.calls[1][1:]] == ["question two"]


def test_rate_limited_request_does_not_call_llm_or_touch_history() -> None:
    llm = FakeLLM(["only answer"])
    engine, _, clock = _engine(llm, cooldown=10.0)

    engine.handle("alice", "first", message_limit=2000)
    clock.now = 4.0
    blocked = engine.handle("alice", "second", message_limit=2000)

    assert blocked.kind == "rate_limited"
    assert blocked.retry_after == pytest.approx(6.0)
    assert len(llm.calls) == 1


def test_users_have_separate_history_and_cooldowns() -> None:
    llm = FakeLLM(["for alice", "for bob"])
    engine, _, _ = _engine(llm)

    engine.handle("alice", "alice question", message_limit=2000)
    result = engine.handle("bob", "bob question", message_limit=2000)

    assert result.kind == "reply"
    assert [m.content for m in llm.calls[1][1:]] == ["bob question"]


def test_llm_error_propagates_and_leaves_history_unchanged() -> None:
    llm = FakeLLM([LLMError("down"), "recovered"])
    engine, _, clock = _engine(llm, cooldown=1.0)

    with pytest.raises(LLMError):
        engine.handle("alice", "first", message_limit=2000)
    clock.now = 5.0
    engine.handle("alice", "second", message_limit=2000)

    assert [m.content for m in llm.calls[1][1:]] == ["second"]


def test_trimmed_history_never_starts_with_assistant_turn() -> None:
    llm = FakeLLM(["a" * 40, "b" * 40, "c" * 40])
    engine, _, clock = _engine(llm, cooldown=1.0, memory_max_tokens=13)

    for turn in range(3):
        clock.now = turn * 5.0
        engine.handle("alice", f"question {turn}", message_limit=2000)

    history = [(m.role, m.content) for m in llm.calls[2][1:-1]]
    assert history == [("user", "question 1"), ("assistant", "b" * 40)]


def test_context_includes_github_link_from_project_frontmatter() -> None:
    llm = FakeLLM(["reply"])
    hit = _page(
        "projects/etl.md",
        "An ETL agent.",
        frontmatter={"links": "[https://github.com/me/etl-agent]"},
    )
    engine, _, _ = _engine(llm, retriever=FakeRetriever([hit]))

    engine.handle("alice", "tell me about the etl project", message_limit=2000)

    system = llm.calls[0][0]
    assert "GitHub: https://github.com/me/etl-agent" in system.content


def test_context_includes_page_link_when_site_url_configured() -> None:
    llm = FakeLLM(["reply"])
    hit = _page("projects/etl.md", "An ETL agent.")
    engine, _, _ = _engine(
        llm,
        retriever=FakeRetriever([hit]),
        site_base_url="https://vaibhavee89.github.io/Career-Brain/",
    )

    engine.handle("alice", "tell me about the etl project", message_limit=2000)

    system = llm.calls[0][0]
    assert (
        "Page link: https://vaibhavee89.github.io/Career-Brain/pages/projects--etl.html"
        in system.content
    )


def test_no_page_link_when_site_url_not_configured() -> None:
    llm = FakeLLM(["reply"])
    hit = _page("projects/etl.md", "An ETL agent.")
    engine, _, _ = _engine(llm, retriever=FakeRetriever([hit]))

    engine.handle("alice", "tell me about the etl project", message_limit=2000)

    assert "Page link:" not in llm.calls[0][0].content


def test_resume_keyword_pulls_in_resume_page_even_if_not_top_matched() -> None:
    llm = FakeLLM(["reply"])
    etl_hit = _page("projects/etl.md", "An ETL agent.")
    resume_hit = _page("profile/resume-variants/eng.md", "Resume content.")

    class RoutingRetriever(FakeRetriever):
        def search(self, query: str, limit: int = 5) -> list[SearchResult]:
            self.queries.append(query)
            if query == "resume cv":
                return [resume_hit][:limit]
            return [etl_hit][:limit]

    engine, retriever, _ = _engine(llm, retriever=RoutingRetriever())

    engine.handle("alice", "can I get your resume?", message_limit=2000)

    system = llm.calls[0][0]
    assert "profile/resume-variants/eng.md" in system.content
    assert "resume cv" in retriever.queries


def test_no_extra_search_when_message_has_no_resume_keywords() -> None:
    llm = FakeLLM(["reply"])
    engine, retriever, _ = _engine(llm)

    engine.handle("alice", "what did you build?", message_limit=2000)

    assert retriever.queries == ["what did you build?"]


def test_resume_hit_not_duplicated_when_already_in_top_results() -> None:
    llm = FakeLLM(["reply"])
    resume_hit = _page("profile/resume-variants/eng.md", "Resume content.")

    class RoutingRetriever(FakeRetriever):
        def search(self, query: str, limit: int = 5) -> list[SearchResult]:
            self.queries.append(query)
            return [resume_hit][:limit]

    engine, _, _ = _engine(llm, retriever=RoutingRetriever())

    result = engine.handle("alice", "send me your resume", message_limit=2000)

    assert result.sources == ["profile/resume-variants/eng.md"]


def test_resume_hit_shares_download_link_not_page_link() -> None:
    llm = FakeLLM(["reply"])
    resume_hit = _page("profile/resume-variants/eng.md", "Resume content.")

    class RoutingRetriever(FakeRetriever):
        def search(self, query: str, limit: int = 5) -> list[SearchResult]:
            self.queries.append(query)
            return [resume_hit][:limit]

    engine = Engine(
        retriever=RoutingRetriever(),
        llm=llm,
        limiter=CooldownLimiter(10.0),
        site_base_url="https://vaibhavee89.github.io/Career-Brain",
        resume_url="https://drive.google.com/file/d/abc/view",
    )

    engine.handle("alice", "can I get your resume?", message_limit=2000)

    system = llm.calls[0][0].content
    assert "Resume download link: https://drive.google.com/file/d/abc/view" in system
    assert "Page link:" not in system
