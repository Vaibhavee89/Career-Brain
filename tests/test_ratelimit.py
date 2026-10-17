import pytest

from careerbrain.core.ratelimit import CooldownLimiter


class FakeClock:
    def __init__(self, now: float = 0.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def test_first_request_is_allowed() -> None:
    limiter = CooldownLimiter(10, clock=FakeClock())
    assert limiter.allow("alice")


def test_second_request_within_cooldown_is_denied() -> None:
    clock = FakeClock()
    limiter = CooldownLimiter(10, clock=clock)
    assert limiter.allow("alice")
    clock.now = 9.5
    assert not limiter.allow("alice")


def test_request_allowed_again_after_cooldown() -> None:
    clock = FakeClock()
    limiter = CooldownLimiter(10, clock=clock)
    assert limiter.allow("alice")
    clock.now = 10.0
    assert limiter.allow("alice")


def test_cooldown_is_per_user() -> None:
    clock = FakeClock()
    limiter = CooldownLimiter(10, clock=clock)
    assert limiter.allow("alice")
    assert limiter.allow("bob")
    assert not limiter.allow("alice")


def test_denied_request_does_not_extend_cooldown() -> None:
    clock = FakeClock()
    limiter = CooldownLimiter(10, clock=clock)
    assert limiter.allow("alice")
    clock.now = 5.0
    assert not limiter.allow("alice")
    clock.now = 10.0
    assert limiter.allow("alice")


def test_retry_after_reports_remaining_cooldown() -> None:
    clock = FakeClock()
    limiter = CooldownLimiter(10, clock=clock)
    assert limiter.retry_after("alice") == 0.0
    limiter.allow("alice")
    clock.now = 4.0
    assert limiter.retry_after("alice") == pytest.approx(6.0)
    clock.now = 20.0
    assert limiter.retry_after("alice") == 0.0


def test_rejects_non_positive_cooldown() -> None:
    with pytest.raises(ValueError):
        CooldownLimiter(0)
