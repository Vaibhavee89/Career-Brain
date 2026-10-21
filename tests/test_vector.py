import json

import httpx

from careerbrain.core.semantic import SemanticRetriever
from careerbrain.core.types import Page
from careerbrain.core.vector import PineconeIndex, from_env

HOST = "career-brain-test.svc.example.pinecone.io"


def _page(path: str, body: str) -> Page:
    return Page(path=path, frontmatter={"public": "true"}, body=body)


class FakePinecone:
    """Answers like Pinecone's documents API, and records every request."""

    def __init__(self, matches: list[str] | None = None, fail: bool = False) -> None:
        self.requests: list[tuple[str, dict]] = []
        self.matches = matches or []
        self.fail = fail

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content or b"{}")
        self.requests.append((request.url.path, body))
        assert request.headers["X-Pinecone-Api-Version"] == "2026-07"
        if self.fail:
            return httpx.Response(500, json={"message": "boom"})
        if request.url.path.endswith("/documents/search"):
            return httpx.Response(
                200, json={"matches": [{"_id": p} for p in self.matches]}
            )
        if request.url.path.endswith("/documents/delete"):
            return httpx.Response(200, json={})
        if request.url.path.endswith("/documents/upsert"):
            return httpx.Response(200, json={"upserted_count": len(body["documents"])})
        return httpx.Response(404, json={})


def _index(fake: FakePinecone) -> PineconeIndex:
    return PineconeIndex(
        "test-key", HOST, client=httpx.Client(transport=httpx.MockTransport(fake))
    )


def test_sync_clears_namespace_then_upserts_one_document_per_page() -> None:
    fake = FakePinecone()
    pages = [
        _page("projects/a.md", "# A\n\nFirst."),
        _page("projects/b.md", "# B\n\nSecond."),
    ]

    assert _index(fake).sync(pages) == 2

    paths = [path for path, _ in fake.requests]
    assert paths == [
        "/namespaces/public-pages/documents/delete",
        "/namespaces/public-pages/documents/upsert",
    ]
    assert fake.requests[0][1] == {"delete_all": True}
    docs = fake.requests[1][1]["documents"]
    assert [d["_id"] for d in docs] == ["projects/a.md", "projects/b.md"]
    assert docs[0]["title"] == "A" and docs[0]["chunk_text"].startswith("A. First.")


def test_sync_sends_large_collections_in_batches() -> None:
    fake = FakePinecone()
    pages = [_page(f"projects/p{i}.md", f"# P{i}\n\nText.") for i in range(100)]

    _index(fake).sync(pages)

    upserts = [body for path, body in fake.requests if path.endswith("/upsert")]
    assert [len(u["documents"]) for u in upserts] == [96, 4]


def test_search_uses_embed_scoring_on_chunk_text() -> None:
    fake = FakePinecone(matches=["projects/a.md"])

    assert _index(fake).search_paths("side projects", limit=3) == ["projects/a.md"]

    _, body = fake.requests[0]
    assert body["top_k"] == 3
    assert body["score_by"] == [
        {"type": "embed", "field": "chunk_text", "query": "side projects"}
    ]


def test_from_env_needs_both_key_and_host() -> None:
    assert from_env({}) is None
    assert from_env({"PINECONE_API_KEY": "k"}) is None
    assert isinstance(
        from_env({"PINECONE_API_KEY": "k", "PINECONE_INDEX_HOST": HOST}), PineconeIndex
    )


class CountingLLM:
    def __init__(self) -> None:
        self.calls = 0

    def complete(self, messages):  # type: ignore[no-untyped-def]
        self.calls += 1
        return '["profile/skills.md"]'


class Source:
    def __init__(self) -> None:
        self.keyword_queries: list[str] = []
        self.pages = [
            _page("projects/a.md", "# A\n\nA."),
            _page("profile/skills.md", "# S\n\nS."),
        ]

    def list_public_pages(self) -> list[Page]:
        return list(self.pages)

    def search(self, query: str, limit: int = 5):  # type: ignore[no-untyped-def]
        self.keyword_queries.append(query)
        return []


def test_retriever_uses_pinecone_and_skips_the_llm_router() -> None:
    llm = CountingLLM()
    retriever = SemanticRetriever(
        Source(), llm, vectors=_index(FakePinecone(matches=["projects/a.md"]))
    )

    results = retriever.search("anything", limit=2)

    assert [r.page.path for r in results] == ["projects/a.md"]
    assert llm.calls == 0


def test_retriever_falls_back_to_llm_router_when_pinecone_fails() -> None:
    llm = CountingLLM()
    retriever = SemanticRetriever(
        Source(), llm, vectors=_index(FakePinecone(fail=True))
    )

    results = retriever.search("skills", limit=2)

    assert [r.page.path for r in results] == ["profile/skills.md"]
    assert llm.calls == 1
