from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal, Protocol

from careerbrain.core.llm import LLMProvider
from careerbrain.core.memory import DEFAULT_RESET_PREFIX, ConversationMemory, Message
from careerbrain.core.ratelimit import CooldownLimiter
from careerbrain.core.splitter import split_message
from careerbrain.core.types import SearchResult

CONTEXT_LIMIT = 3
PAGE_CHAR_LIMIT = 2000
BASE_PROMPT = (
    "You answer questions about a person's career using only the context below. "
    "If the context does not contain the answer, say so. "
    "Write in plain English prose, like a short spoken answer. "
    "Do not use markdown: no headers, no asterisks or bold, no bullet lists, "
    "no emoji. Use full sentences and, if you need to list a few things, "
    "write them as a sentence separated by commas, not a list."
)


class Retriever(Protocol):
    def search(self, query: str, limit: int = 5) -> list[SearchResult]: ...


@dataclass(frozen=True)
class EngineResult:
    kind: Literal["reply", "reset", "rate_limited"]
    chunks: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    retry_after: float = 0.0


class Engine:
    def __init__(
        self,
        retriever: Retriever,
        llm: LLMProvider,
        limiter: CooldownLimiter,
        memory_max_tokens: int = 2000,
        reset_prefix: str = DEFAULT_RESET_PREFIX,
    ) -> None:
        self._retriever = retriever
        self._llm = llm
        self._limiter = limiter
        self._memory_max_tokens = memory_max_tokens
        self._reset_prefix = reset_prefix
        self._memories: dict[str, ConversationMemory] = {}

    def reset(self, conversation_key: str) -> None:
        self._memory_for(conversation_key).reset()

    def handle(
        self,
        user_id: str,
        text: str,
        message_limit: int,
        conversation_key: str | None = None,
    ) -> EngineResult:
        memory = self._memory_for(conversation_key or user_id)
        if memory.is_reset_command(text):
            memory.reset()
            return EngineResult(kind="reset")

        if not self._limiter.allow(user_id):
            return EngineResult(
                kind="rate_limited", retry_after=self._limiter.retry_after(user_id)
            )

        hits = self._retriever.search(text, limit=CONTEXT_LIMIT)
        messages = [
            Message("system", _system_prompt(hits)),
            *memory.messages(),
            Message("user", text),
        ]
        reply = self._llm.complete(messages)

        memory.add_user(text)
        memory.add_assistant(reply)
        return EngineResult(
            kind="reply",
            chunks=split_message(reply, message_limit),
            sources=[hit.page.path for hit in hits],
        )

    def _memory_for(self, user_id: str) -> ConversationMemory:
        if user_id not in self._memories:
            self._memories[user_id] = ConversationMemory(
                max_tokens=self._memory_max_tokens,
                reset_prefix=self._reset_prefix,
            )
        return self._memories[user_id]


def _system_prompt(hits: Sequence[SearchResult]) -> str:
    if not hits:
        return f"{BASE_PROMPT}\n\nNo matching pages were found in the brain."
    context = "\n\n".join(
        f"[source: {hit.page.path}]\n{hit.page.body[:PAGE_CHAR_LIMIT]}" for hit in hits
    )
    return f"{BASE_PROMPT}\n\nContext from the brain:\n\n{context}"
