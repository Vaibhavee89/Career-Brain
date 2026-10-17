from __future__ import annotations

import time
from collections.abc import Callable, Hashable

Clock = Callable[[], float]


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
