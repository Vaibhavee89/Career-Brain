from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

Role = Literal["system", "user", "assistant"]
TokenCounter = Callable[[str], int]

DEFAULT_RESET_PREFIX = "/reset"


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


@dataclass(frozen=True)
class Message:
    role: Role
    content: str


class ConversationMemory:
    def __init__(
        self,
        max_tokens: int,
        reset_prefix: str = DEFAULT_RESET_PREFIX,
        count_tokens: TokenCounter = estimate_tokens,
    ) -> None:
        if max_tokens <= 0:
            raise ValueError("max_tokens must be positive")
        self._max_tokens = max_tokens
        self._reset_prefix = reset_prefix.lower()
        self._count_tokens = count_tokens
        self._messages: list[Message] = []

    def add_user(self, content: str) -> None:
        self._append(Message("user", content))

    def add_assistant(self, content: str) -> None:
        self._append(Message("assistant", content))

    def messages(self) -> list[Message]:
        return list(self._messages)

    def reset(self) -> None:
        self._messages.clear()

    def is_reset_command(self, text: str) -> bool:
        return text.strip().lower().startswith(self._reset_prefix)

    def _append(self, message: Message) -> None:
        self._messages.append(message)
        self._messages = self._trim(self._messages)

    def _trim(self, messages: list[Message]) -> list[Message]:
        kept: list[Message] = []
        used = 0
        for message in reversed(messages):
            cost = self._count_tokens(message.content)
            if used + cost > self._max_tokens:
                break
            kept.append(message)
            used += cost
        kept.reverse()
        while kept and kept[0].role != "user":
            kept.pop(0)
        return kept
