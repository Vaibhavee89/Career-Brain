from collections.abc import Sequence

from careerbrain.core.answer_cache import AnswerCache, data_version, normalize_question
from careerbrain.core.engine import Engine
from careerbrain.core.llm import LLMError
from careerbrain.core.memory import Message
from careerbrain.core.ratelimit import CooldownLimiter
from careerbrain.core.types import Page, SearchResult


class CountingLLM:
    def __init__(self, replies: Sequence[str]) -> None:
        self._replies = list(replies)
        self.calls = 0

    def complete(self, messages: Sequence[Message]) -> str:
        self.calls += 1
        return self._replies.pop(0)


class FakeRetriever:
    def __init__(self) -> None:
        self.queries: list[str] = []

    def search(self, query: str, limit: int = 5) -> list[SearchResult]:
        self.queries.append(query)
        page = Page(path="projects/etl.md", frontmatter={"public": "true"}, body="etl")
        return [SearchResult(page=page, score=1, snippet="")]


class Ticking:
    """A clock that moves forward on every read, so the cooldown never blocks a test."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        self.now += 10.0
        return self.now


def _engine(llm: CountingLLM, retriever: FakeRetriever, version: str = "v1") -> Engine:
    return Engine(
        retriever=retriever,
        llm=llm,
        limiter=CooldownLimiter(1.0, clock=Ticking()),
        cache=AnswerCache(),
        data_version=version,
    )


def test_normalize_ignores_case_spacing_and_trailing_punctuation() -> None:
    assert (
        normalize_question("  What's  her STRONGEST project?? ")
        == "what's her strongest project"
    )


def test_repeated_stateless_question_is_served_from_cache() -> None:
    llm = CountingLLM(["The DP Agent."])
    retriever = FakeRetriever()
    engine = _engine(llm, retriever)

    first = engine.handle("alice", "What is the DP Agent?", message_limit=2000)
    second = engine.handle("bob", "what is the dp agent", message_limit=2000)

    assert llm.calls == 1
    assert second.chunks == first.chunks == ["The DP Agent."]
    assert second.sources == ["projects/etl.md"]
    assert len(retriever.queries) == 1


def test_cached_answer_still_counts_in_the_users_history() -> None:
    llm = CountingLLM(["The DP Agent.", "Follow-up answer."])
    engine = _engine(llm, FakeRetriever())

    engine.handle("alice", "What is the DP Agent?", message_limit=2000)
    engine.handle("bob", "what is the dp agent", message_limit=2000)
    engine.handle("bob", "and who built it?", message_limit=2000)

    assert (
        llm.calls == 2
    )  # the follow-up has history, so it is not cached and reaches the model


def test_questions_with_history_are_not_cached() -> None:
    llm = CountingLLM(["one", "two"])
    engine = _engine(llm, FakeRetriever())

    engine.handle("alice", "first question", message_limit=2000)
    engine.handle("alice", "same question", message_limit=2000)

    assert llm.calls == 2


def test_a_changed_data_version_misses_the_cache() -> None:
    cache = AnswerCache()
    cache.put("v1|||what is x", "old answer", ["a.md"])
    assert cache.get("v2|||what is x") is None
    assert cache.get("v1|||what is x") == ("old answer", ["a.md"])


def test_failed_llm_calls_are_not_cached() -> None:
    class Failing:
        calls = 0

        def complete(self, messages):  # type: ignore[no-untyped-def]
            self.calls += 1
            raise LLMError("down")

    llm = Failing()
    engine = Engine(
        retriever=FakeRetriever(),
        llm=llm,
        limiter=CooldownLimiter(1.0, clock=Ticking()),
        cache=AnswerCache(),
        data_version="v1",
    )
    for _ in range(2):
        try:
            engine.handle("alice", "question", message_limit=2000)
        except LLMError:
            pass
    assert llm.calls == 2


def test_cache_is_bounded() -> None:
    cache = AnswerCache(max_entries=2)
    cache.put("a", "1", [])
    cache.put("b", "2", [])
    cache.put("c", "3", [])
    assert len(cache) == 2
    assert cache.get("a") is None


def test_data_version_changes_when_public_content_changes() -> None:
    before = [Page(path="a.md", frontmatter={}, body="one")]
    after = [Page(path="a.md", frontmatter={}, body="two")]
    assert data_version(before) != data_version(after)
    assert data_version(before) == data_version(list(reversed(before)))
