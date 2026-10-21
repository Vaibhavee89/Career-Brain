from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from typing import Any

import httpx

from careerbrain.core.types import Page, page_title

API_VERSION = "2026-07"
NAMESPACE = "public-pages"
EMBED_FIELD = "chunk_text"
SUMMARY_CHARS = 400
BATCH = 96
API_KEY_ENV = "PINECONE_API_KEY"
INDEX_HOST_ENV = "PINECONE_INDEX_HOST"


class PineconeIndex:
    """Public pages in a Pinecone index with integrated embeddings.

    The index embeds `chunk_text` itself (llama-text-embed-v2), so this client only
    sends text. Each page is one document, with its path as the document id.
    """

    def __init__(
        self, api_key: str, index_host: str, client: httpx.Client | None = None
    ) -> None:
        self._headers = {
            "Api-Key": api_key,
            "Content-Type": "application/json",
            "X-Pinecone-Api-Version": API_VERSION,
        }
        self._base = f"https://{index_host.removeprefix('https://').rstrip('/')}"
        self._client = client or httpx.Client(timeout=30.0)

    def sync(self, pages: Sequence[Page]) -> int:
        """Replace the namespace so only the current public pages are searchable."""
        self._post("/documents/delete", {"delete_all": True}, allow_missing=True)
        documents = [
            {
                "_id": page.path,
                "title": page_title(page),
                EMBED_FIELD: _index_text(page),
            }
            for page in pages
        ]
        for start in range(0, len(documents), BATCH):
            self._post(
                "/documents/upsert", {"documents": documents[start : start + BATCH]}
            )
        return len(documents)

    def search_paths(self, query: str, limit: int) -> list[str]:
        data = self._post(
            "/documents/search",
            {
                "top_k": limit,
                "score_by": [{"type": "embed", "field": EMBED_FIELD, "query": query}],
                "include_fields": ["title"],
            },
        )
        return [match["_id"] for match in data.get("matches", []) if "_id" in match]

    def _post(
        self, path: str, body: Mapping[str, Any], allow_missing: bool = False
    ) -> dict[str, Any]:
        response = self._client.post(
            f"{self._base}/namespaces/{NAMESPACE}{path}",
            headers=self._headers,
            json=dict(body),
        )
        # Deleting from a namespace that was never written to has nothing to remove.
        if allow_missing and response.status_code == 404:
            return {}
        response.raise_for_status()
        return response.json()


def _index_text(page: Page) -> str:
    body = " ".join(
        line for line in page.body.splitlines() if not line.startswith("# ")
    ).split()
    return f"{page_title(page)}. {' '.join(body)[:SUMMARY_CHARS]}"


def from_env(environ: Mapping[str, str] | None = None) -> PineconeIndex | None:
    env: Mapping[str, str] = os.environ if environ is None else environ
    api_key = env.get(API_KEY_ENV)
    host = env.get(INDEX_HOST_ENV)
    if not api_key or not host:
        return None
    return PineconeIndex(api_key, host)


def sync_vectors(
    brain: Any, environ: Mapping[str, str] | None = None
) -> PineconeIndex | None:
    """Sync `brain`'s public pages into Pinecone.

    Returns None if Pinecone isn't configured or the sync fails, so the chat
    keeps working on keyword search.
    """
    index = from_env(environ)
    if index is None:
        return None
    try:
        index.sync(brain.list_public_pages())
    except httpx.HTTPError as exc:
        print(f"pinecone: sync failed, using keyword search: {exc}")
        return None
    return index
