from __future__ import annotations

import json
import re
from collections.abc import Sequence
from typing import Protocol

import httpx

from careerbrain.core.llm import LLMError, LLMProvider
from careerbrain.core.memory import Message
from careerbrain.core.types import Page, SearchResult, page_title
from careerbrain.core.vector import PineconeIndex

SUMMARY_CHARS = 400
ARRAY = re.compile(r"\[.*\]", re.DOTALL)
ROUTER_PROMPT = (
    "You choose which pages from a personal knowledge base help answer a question. "
    "Match by meaning, not only by shared words: 'side projects' can mean projects, "
    "'how do you build things' can mean engineering decisions. Reply with only a JSON "
    "array of up to {limit} page paths, copied exactly from the list, most relevant "
    "first. Reply [] if no page is relevant."
)


class PageSource(Protocol):
    def list_public_pages(self) -> list[Page]: ...

    def search(self, query: str, limit: int = 5) -> list[SearchResult]: ...


class SemanticRetriever:
    """Picks pages by meaning with the LLM, falling back to keyword search.

    The public knowledge base is small, so the model sees a short index of
    every public page and returns the paths that answer the question. Anything
    it returns that isn't a public page is ignored.
    """

    def __init__(
        self,
        source: PageSource,
        llm: LLMProvider,
        vectors: PineconeIndex | None = None,
    ) -> None:
        self._source = source
        self._llm = llm
        self._vectors = vectors

    def search(self, query: str, limit: int = 5) -> list[SearchResult]:
        pages = self._source.list_public_pages()
        if not pages:
            return []
        if self._vectors is not None:
            found = self._search_vectors(query, limit, pages)
            if found is not None:
                return found
        try:
            reply = self._llm.complete(
                [
                    Message("system", ROUTER_PROMPT.format(limit=limit)),
                    Message("user", f"Question: {query}\n\nPages:\n{_index(pages)}"),
                ]
            )
        except LLMError:
            return self._source.search(query, limit=limit)

        paths = _parse_paths(reply)
        if paths is None:
            return self._source.search(query, limit=limit)

        by_path = {page.path: page for page in pages}
        results: list[SearchResult] = []
        for path in paths:
            page = by_path.get(path)
            if page is None or any(r.page.path == path for r in results):
                continue
            results.append(
                SearchResult(page=page, score=limit - len(results), snippet="")
            )
            if len(results) == limit:
                break
        return results or self._source.search(query, limit=limit)

    def _search_vectors(
        self, query: str, limit: int, pages: Sequence[Page]
    ) -> list[SearchResult] | None:
        assert self._vectors is not None
        try:
            paths = self._vectors.search_paths(query, limit)
        except (httpx.HTTPError, KeyError, ValueError):
            return None
        by_path = {page.path: page for page in pages}
        results = [
            SearchResult(page=by_path[path], score=limit - i, snippet="")
            for i, path in enumerate(dict.fromkeys(paths))
            if path in by_path
        ][:limit]
        return results or None


def _index(pages: Sequence[Page]) -> str:
    lines = []
    for page in pages:
        body = "\n".join(
            line for line in page.body.splitlines() if not line.startswith("# ")
        )
        summary = " ".join(body.split())[:SUMMARY_CHARS]
        lines.append(f"- {page.path} | {page_title(page)} | {summary}")
    return "\n".join(lines)


def _parse_paths(reply: str) -> list[str] | None:
    match = ARRAY.search(reply)
    if match is None:
        return None
    try:
        value = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(value, list):
        return None
    return [item for item in value if isinstance(item, str)]
