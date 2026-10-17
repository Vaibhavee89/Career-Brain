from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable, Hashable

Clock = Callable[[], float]


class WindowLimiter:
    def __init__(
        self,
        max_requests: int,
        window_seconds: float,
        clock: Clock = time.monotonic,
    ) -> None:
        if max_requests <= 0 or window_seconds <= 0:
            raise ValueError("max_requests and window_seconds must be positive")
        self._max = max_requests
        self._window = window_seconds
        self._clock = clock
        self._hits: dict[Hashable, deque[float]] = {}

    def retry_after(self, key: Hashable) -> float:
        now = self._clock()
        hits = self._hits.get(key)
        if hits is None:
            return 0.0
        while hits and hits[0] <= now - self._window:
            hits.popleft()
        if not hits:
            del self._hits[key]
            return 0.0
        if len(hits) < self._max:
            return 0.0
        return max(0.0, hits[0] + self._window - now)

    def allow(self, key: Hashable) -> bool:
        if self.retry_after(key) > 0:
            return False
        self._hits.setdefault(key, deque()).append(self._clock())
        return True


class CooldownLimiter:
    def __init__(self, cooldown_seconds: float, clock: Clock = time.monotonic) -> None:
        if cooldown_seconds <= 0:
            raise ValueError("cooldown_seconds must be positive")
        self._cooldown = cooldown_seconds
        self._clock = clock
        self._last_allowed: dict[Hashable, float] = {}

    def retry_after(self, user_id: Hashable) -> float:
        last = self._last_allowed.get(user_id)
        if last is None:
            return 0.0
        return max(0.0, last + self._cooldown - self._clock())

    def allow(self, user_id: Hashable) -> bool:
        if self.retry_after(user_id) > 0:
            return False
        self._last_allowed[user_id] = self._clock()
        return True
