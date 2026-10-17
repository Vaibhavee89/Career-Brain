from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from typing import Protocol

import httpx

from careerbrain.core.memory import Message

GROQ_CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"
DEFAULT_MODEL = "openai/gpt-oss-120b"
RETRYABLE_STATUS = frozenset({429}) | frozenset(range(500, 600))

Sleep = Callable[[float], None]


class LLMError(RuntimeError):
    pass


class LLMProvider(Protocol):
    def complete(self, messages: Sequence[Message]) -> str: ...


class GroqProvider:
    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_MODEL,
        *,
        transport: httpx.BaseTransport | None = None,
        max_retries: int = 4,
        base_delay: float = 1.0,
        max_delay: float = 30.0,
        sleep: Sleep = time.sleep,
    ) -> None:
        self._model = model
        self._max_retries = max_retries
        self._base_delay = base_delay
        self._max_delay = max_delay
        self._sleep = sleep
        self._client = httpx.Client(
            transport=transport,
            timeout=30.0,
            headers={"Authorization": f"Bearer {api_key}"},
        )

    def complete(self, messages: Sequence[Message]) -> str:
        payload = {
            "model": self._model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
        }
        for attempt in range(self._max_retries + 1):
            try:
                response = self._client.post(GROQ_CHAT_URL, json=payload)
            except httpx.TransportError as exc:
                if attempt == self._max_retries:
                    raise LLMError(f"Groq connection failed: {exc}") from exc
                self._sleep(self._backoff(attempt, None))
                continue

            if response.status_code in RETRYABLE_STATUS:
                if attempt == self._max_retries:
                    raise LLMError(
                        f"Groq returned {response.status_code} after retries"
                    )
                self._sleep(self._backoff(attempt, response.headers.get("retry-after")))
                continue

            if response.status_code >= 400:
                raise LLMError(f"Groq returned {response.status_code}: {response.text}")

            return _extract_content(response)

        raise LLMError("unreachable: retry loop exited without a result")

    def _backoff(self, attempt: int, retry_after: str | None) -> float:
        if retry_after is not None:
            try:
                return min(float(retry_after), self._max_delay)
            except ValueError:
                pass
        return min(self._base_delay * (2**attempt), self._max_delay)

    def close(self) -> None:
        self._client.close()


def _extract_content(response: httpx.Response) -> str:
    try:
        return response.json()["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise LLMError("unexpected Groq response shape") from exc
