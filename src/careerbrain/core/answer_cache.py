from __future__ import annotations

import hashlib
import re
from collections import OrderedDict
from collections.abc import Sequence

from careerbrain.core.types import Page

DEFAULT_SIZE = 500
_SPACES = re.compile(r"\s+")
_TRAILING = re.compile(r"[\s?.!]+$")


def normalize_question(text: str) -> str:
    """Lowercase, collapse whitespace, and drop trailing punctuation."""
    return _TRAILING.sub("", _SPACES.sub(" ", text.strip().lower()))


def data_version(pages: Sequence[Page]) -> str:
    """A fingerprint of the public content. Any change to a page changes it."""
    digest = hashlib.sha256()
    for page in sorted(pages, key=lambda p: p.path):
        digest.update(page.path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(page.body.encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()[:16]


class AnswerCache:
    """A bounded, in-memory map from question to its last reply.

    Keys include the data version, so an answer is never served after the
    public content changed. Only stateless questions are cached, because a
    conversation's history changes what a reply should say.
    """

    def __init__(self, max_entries: int = DEFAULT_SIZE) -> None:
        self._max = max_entries
        self._items: OrderedDict[str, tuple[str, list[str]]] = OrderedDict()

    def get(self, key: str) -> tuple[str, list[str]] | None:
        entry = self._items.get(key)
        if entry is not None:
            self._items.move_to_end(key)
        return entry

    def put(self, key: str, reply: str, sources: list[str]) -> None:
        self._items[key] = (reply, sources)
        self._items.move_to_end(key)
        while len(self._items) > self._max:
            self._items.popitem(last=False)

    def __len__(self) -> int:
        return len(self._items)
