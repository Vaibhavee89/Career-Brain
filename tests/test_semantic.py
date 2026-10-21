from collections.abc import Sequence

from careerbrain.core.llm import LLMError
from careerbrain.core.memory import Message
from careerbrain.core.semantic import SemanticRetriever
from careerbrain.core.types import Page, SearchResult


class FakeLLM:
    def __init__(self, reply: str | Exception) -> None:
        self._reply = reply
        self.calls: list[list[Message]] = []

    def complete(self, messages: Sequence[Message]) -> str:
        self.calls.append(list(messages))
        if isinstance(self._reply, Exception):
            raise self._reply
        return self._reply


class FakeSource:
    def __init__(self, pages: list[Page]) -> None:
        self._pages = pages
        self.keyword_queries: list[str] = []

    def list_public_pages(self) -> list[Page]:
        return list(self._pages)

    def search(self, query: str, limit: int = 5) -> list[SearchResult]:
        self.keyword_queries.append(query)
        return [SearchResult(page=self._pages[0], score=1, snippet="")][:limit]


def _page(path: str, body: str) -> Page:
    return Page(path=path, frontmatter={"public": "true"}, body=body)


PAGES = [
    _page("projects/dp-agent.md", "# DP Agent\n\nDiagnoses failed Airflow DAGs."),
    _page("projects/netaudit.md", "# NetAudit\n\nNetwork scanning with Flask."),
    _page("profile/skills.md", "# Skills\n\nPython, SQL, MCP."),
]


def test_model_picks_pages_by_meaning_in_its_order() -> None:
    llm = FakeLLM('["projects/netaudit.md", "projects/dp-agent.md"]')
    retriever = SemanticRetriever(FakeSource(PAGES), llm)

    results = retriever.search("what side projects have you built?", limit=2)

    assert [r.page.path for r in results] == [
        "projects/netaudit.md",
        "projects/dp-agent.md",
    ]
    assert "projects/dp-agent.md" in llm.calls[0][1].content


def test_paths_that_are_not_public_pages_are_ignored() -> None:
    llm = FakeLLM('["projects/secret.md", "profile/skills.md"]')
    retriever = SemanticRetriever(FakeSource(PAGES), llm)

    results = retriever.search("skills", limit=3)

    assert [r.page.path for r in results] == ["profile/skills.md"]


def test_duplicate_paths_and_limit_are_respected() -> None:
    llm = FakeLLM(
        '["projects/dp-agent.md", "projects/dp-agent.md", "profile/skills.md"]'
    )
    retriever = SemanticRetriever(FakeSource(PAGES), llm)

    results = retriever.search("anything", limit=1)

    assert [r.page.path for r in results] == ["projects/dp-agent.md"]


def test_unparseable_reply_falls_back_to_keyword_search() -> None:
    source = FakeSource(PAGES)
    retriever = SemanticRetriever(source, FakeLLM("Sorry, I can't pick pages."))

    retriever.search("airflow", limit=2)

    assert source.keyword_queries == ["airflow"]


def test_llm_error_falls_back_to_keyword_search() -> None:
    source = FakeSource(PAGES)
    retriever = SemanticRetriever(source, FakeLLM(LLMError("down")))

    retriever.search("airflow", limit=2)

    assert source.keyword_queries == ["airflow"]


def test_no_public_pages_returns_nothing_without_calling_the_model() -> None:
    llm = FakeLLM("[]")
    assert SemanticRetriever(FakeSource([]), llm).search("anything") == []
    assert llm.calls == []
