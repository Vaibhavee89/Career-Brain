from __future__ import annotations

import os
import re
import time
from collections import OrderedDict
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from careerbrain.adapters.cli import OfflineLLM
from careerbrain.bootstrap import open_brain
from careerbrain.core.answer_cache import AnswerCache, data_version
from careerbrain.core.engine import Engine, EngineResult
from careerbrain.core.llm import GroqProvider, LLMError, LLMProvider
from careerbrain.core.ratelimit import CooldownLimiter
from careerbrain.core.semantic import SemanticRetriever
from careerbrain.core.splitter import split_message
from careerbrain.core.vector import sync_vectors

API_KEY_ENV = "GROQ_API_KEY"
SITE_URL_ENV = "CAREERBRAIN_SITE_URL"
RESUME_URL_ENV = "CAREERBRAIN_RESUME_URL"
COOLDOWN_SECONDS = 1.0
DISCORD_MESSAGE_LIMIT = 2_000
SLACK_MESSAGE_LIMIT = 40_000
INBOUND_CHAR_LIMIT = 2_000
EVENT_TTL_SECONDS = 300.0
EVENT_CACHE_SIZE = 1_000
LLM_UNAVAILABLE_TEXT = (
    "Sorry, the language model is unavailable right now. Try again shortly."
)

InboundKind = Literal["message", "reset"]
Clock = Callable[[], float]


@dataclass(frozen=True)
class InboundMessage:
    platform: str
    user_id: str
    conversation_key: str
    text: str
    kind: InboundKind = "message"


def strip_mentions(text: str, bot_ids: Iterable[str]) -> str:
    for bot_id in bot_ids:
        text = re.sub(rf"<@!?{re.escape(bot_id)}>", " ", text)
    return re.sub(r"[ \t]+", " ", text).strip()


def truncate_inbound(text: str) -> str:
    return text[:INBOUND_CHAR_LIMIT]


_CODE_BLOCK = re.compile(r"(```.*?```)", re.DOTALL)
_HEADING = re.compile(r"^#{1,6}\s+(.+)$", re.MULTILINE)
_LINK = re.compile(r"\[([^\]]+)\]\((https?://[^\s)]+)\)")
_BOLD = re.compile(r"\*\*(.+?)\*\*|__(.+?)__")
_ITALIC = re.compile(r"(?<![\w*])\*(?![\s*])(.+?)(?<![\s*])\*(?![\w*])")
_STRIKE = re.compile(r"~~(.+?)~~")
_BOLD_OPEN, _BOLD_CLOSE = "\x01", "\x02"


def to_slack_mrkdwn(text: str) -> str:
    parts = _CODE_BLOCK.split(text)
    return "".join(
        part if index % 2 else _convert_prose(part) for index, part in enumerate(parts)
    )


def _convert_prose(text: str) -> str:
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    text = _HEADING.sub(lambda m: _wrap_bold(m.group(1)), text)
    text = _BOLD.sub(lambda m: _wrap_bold(m.group(1) or m.group(2)), text)
    text = _LINK.sub(r"<\2|\1>", text)
    text = _ITALIC.sub(r"_\1_", text)
    text = _STRIKE.sub(r"~\1~", text)
    return text.replace(_BOLD_OPEN, "*").replace(_BOLD_CLOSE, "*")


def _wrap_bold(content: str) -> str:
    return f"{_BOLD_OPEN}{content}{_BOLD_CLOSE}"


def render_reply(text: str, platform: str, limit: int) -> list[str]:
    body = to_slack_mrkdwn(text) if platform == "slack" else text
    return split_message(body, limit)


class RecentEvents:
    def __init__(
        self,
        ttl: float = EVENT_TTL_SECONDS,
        max_size: int = EVENT_CACHE_SIZE,
        clock: Clock = time.monotonic,
    ) -> None:
        self._ttl = ttl
        self._max_size = max_size
        self._clock = clock
        self._seen: OrderedDict[str, float] = OrderedDict()

    def check_and_add(self, event_id: str) -> bool:
        now = self._clock()
        while self._seen and next(iter(self._seen.values())) <= now - self._ttl:
            self._seen.popitem(last=False)
        if event_id in self._seen:
            return True
        self._seen[event_id] = now
        while len(self._seen) > self._max_size:
            self._seen.popitem(last=False)
        return False


def dispatch(
    engine: Engine,
    message: InboundMessage,
    platform: str,
    limit: int,
) -> list[str]:
    if message.kind == "reset":
        engine.reset(message.conversation_key)
        return ["History cleared."]
    try:
        result = engine.handle(
            message.user_id,
            message.text,
            limit,
            conversation_key=message.conversation_key,
        )
    except LLMError:
        return [LLM_UNAVAILABLE_TEXT]
    return _render_result(result, platform, limit)


def _render_result(result: EngineResult, platform: str, limit: int) -> list[str]:
    if result.kind == "reset":
        return ["History cleared."]
    if result.kind == "rate_limited":
        return [f"Too fast. Try again in {result.retry_after:.0f}s."]
    body = "\n\n".join(result.chunks)
    if result.sources:
        body += f"\n\n(sources: {', '.join(result.sources)})"
    return render_reply(body, platform, limit)


def build_engine(root: Path | None, offline: bool) -> Engine:
    llm: LLMProvider
    if offline:
        llm = OfflineLLM()
    else:
        api_key = os.environ.get(API_KEY_ENV)
        if not api_key:
            raise RuntimeError(f"Set {API_KEY_ENV} or run with --offline.")
        llm = GroqProvider(api_key)
    brain = open_brain(root)
    vectors = None if offline else sync_vectors(brain)
    return Engine(
        retriever=SemanticRetriever(brain, llm, vectors=vectors),
        llm=llm,
        limiter=CooldownLimiter(COOLDOWN_SECONDS),
        site_base_url=os.environ.get(SITE_URL_ENV),
        cache=AnswerCache(),
        data_version=data_version(brain.list_public_pages()),
        resume_url=os.environ.get(RESUME_URL_ENV),
    )
