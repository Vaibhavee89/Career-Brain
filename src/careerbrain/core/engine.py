from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal, Protocol

from careerbrain.core.llm import LLMProvider
from careerbrain.core.memory import DEFAULT_RESET_PREFIX, ConversationMemory, Message
from careerbrain.core.ratelimit import CooldownLimiter
from careerbrain.core.splitter import split_message
from careerbrain.core.types import SearchResult, page_links, page_url

CONTEXT_LIMIT = 4
PAGE_CHAR_LIMIT = 2500
RESUME_QUERY = "resume cv"
RESUME_PAGE_PREFIX = "profile/resume-variants/"
RESUME_TRIGGER_WORDS = ("resume", "cv", "download")
BASE_PROMPT = (
    "You answer questions about Vaibhavee's career using only the context below, "
    "for a visitor who is not Vaibhavee. Refer to Vaibhavee by name or as 'they', "
    "never as 'you' or 'I' — you are not Vaibhavee and are not speaking to them. "
    "If the context does not contain the answer, say so. "
    "Write in plain English prose, like a short spoken answer. "
    "Do not use markdown: no headers, no asterisks or bold, no bullet lists, "
    "no emoji. Use full sentences and, if you need to list a few things, "
    "write them as a sentence separated by commas, not a list. "
    "Keep answers short: 2 to 4 sentences, unless the question explicitly asks "
    "for more detail. "
    "If a context block for a project has a GitHub link, include that link when "
    "you discuss that project. If asked for a resume or CV, share the 'Resume "
    "download link' from the context exactly as written, and do not send the "
    "resume web page instead. Never invent a link that is not in the context."
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
        site_base_url: str | None = None,
        resume_url: str | None = None,
    ) -> None:
        self._retriever = retriever
        self._llm = llm
        self._limiter = limiter
        self._memory_max_tokens = memory_max_tokens
        self._reset_prefix = reset_prefix
        self._site_base_url = site_base_url
        self._resume_url = resume_url
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
        if any(word in text.lower() for word in RESUME_TRIGGER_WORDS):
            hits = _with_resume_hit(hits, self._retriever.search(RESUME_QUERY, limit=1))
        messages = [
            Message(
                "system", _system_prompt(hits, self._site_base_url, self._resume_url)
            ),
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


def _with_resume_hit(
    hits: Sequence[SearchResult], resume_hits: Sequence[SearchResult]
) -> list[SearchResult]:
    seen = {hit.page.path for hit in hits}
    extra = [hit for hit in resume_hits if hit.page.path not in seen]
    return [*hits, *extra]


def _system_prompt(
    hits: Sequence[SearchResult],
    site_base_url: str | None,
    resume_url: str | None = None,
) -> str:
    if not hits:
        return f"{BASE_PROMPT}\n\nNo matching pages were found in the brain."
    context = "\n\n".join(
        _context_block(hit, site_base_url, resume_url) for hit in hits
    )
    return f"{BASE_PROMPT}\n\nContext from the brain:\n\n{context}"


def _context_block(
    hit: SearchResult, site_base_url: str | None, resume_url: str | None = None
) -> str:
    lines = [
        f"[source: {hit.page.path}]",
        hit.page.body[:PAGE_CHAR_LIMIT],
    ]
    links = page_links(hit.page.frontmatter)
    if links:
        lines.append(f"GitHub: {', '.join(links)}")
    if hit.page.path.startswith(RESUME_PAGE_PREFIX) and resume_url:
        lines.append(f"Resume download link: {resume_url}")
    elif site_base_url:
        lines.append(f"Page link: {page_url(site_base_url, hit.page.path)}")
    return "\n".join(lines)
