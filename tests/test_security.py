from collections.abc import Sequence

import pytest
from fastapi.testclient import TestClient

from careerbrain.adapters.client_ip import (
    UNKNOWN_PEER,
    parse_networks,
    resolve_client_ip,
)
from careerbrain.adapters.http_api import build_app
from careerbrain.core.engine import Engine
from careerbrain.core.memory import Message
from careerbrain.core.ratelimit import CooldownLimiter, WindowLimiter
from careerbrain.core.types import SearchResult

PROXY_NET = parse_networks(["10.0.0.0/24"])
ORIGIN = "https://career.example.com"


class FakeRetriever:
    def search(self, query: str, limit: int = 5) -> list[SearchResult]:
        return []


class FakeLLM:
    def __init__(self) -> None:
        self.calls: list[list[Message]] = []

    def complete(self, messages: Sequence[Message]) -> str:
        self.calls.append(list(messages))
        return "ok"


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def _client(
    *,
    cors_origins: Sequence[str] = (),
    trusted_proxies: Sequence[str] = (),
    max_requests: int = 2,
    window: float = 60.0,
    peer: tuple[str, int] = ("203.0.113.9", 50000),
    clock: FakeClock | None = None,
) -> TestClient:
    clock = clock or FakeClock()
    engine = Engine(
        retriever=FakeRetriever(),
        llm=FakeLLM(),
        limiter=CooldownLimiter(0.001, clock=clock),
    )
    app = build_app(
        engine,
        cors_origins=cors_origins,
        trusted_proxies=parse_networks(list(trusted_proxies)),
        ip_limiter=WindowLimiter(max_requests, window, clock=clock),
    )
    return TestClient(app, client=peer)


def _ask(client: TestClient, user: str, **kwargs) -> object:
    return client.post("/ask", json={"user_id": user, "message": "hi"}, **kwargs)


def test_forwarded_for_ignored_when_peer_is_not_trusted() -> None:
    assert resolve_client_ip("203.0.113.9", "1.2.3.4", PROXY_NET) == "203.0.113.9"


def test_forwarded_for_uses_rightmost_untrusted_hop() -> None:
    assert resolve_client_ip("10.0.0.1", "1.2.3.4, 9.9.9.9", PROXY_NET) == "9.9.9.9"


def test_forwarded_for_skips_trusted_hops() -> None:
    assert resolve_client_ip("10.0.0.1", "1.2.3.4, 10.0.0.2", PROXY_NET) == "1.2.3.4"


@pytest.mark.parametrize("forwarded", ["not-an-ip", "1.2.3.4, junk", "10.0.0.2"])
def test_bad_or_all_trusted_forwarded_for_falls_back_to_peer(forwarded: str) -> None:
    assert resolve_client_ip("10.0.0.1", forwarded, PROXY_NET) == "10.0.0.1"


def test_missing_peer_is_labelled_unknown() -> None:
    assert resolve_client_ip(None, None, []) == UNKNOWN_PEER


def test_parse_networks_rejects_garbage() -> None:
    with pytest.raises(ValueError):
        parse_networks(["not-a-network"])


def test_window_limiter_allows_max_then_recovers() -> None:
    clock = FakeClock()
    limiter = WindowLimiter(2, 60.0, clock=clock)
    assert limiter.allow("a")
    assert limiter.allow("a")
    assert not limiter.allow("a")
    assert limiter.retry_after("a") == pytest.approx(60.0)
    clock.now = 60.0
    assert limiter.allow("a")


def test_window_limiter_keys_are_independent() -> None:
    limiter = WindowLimiter(1, 60.0, clock=FakeClock())
    assert limiter.allow("a")
    assert limiter.allow("b")
    assert not limiter.allow("a")


def test_cors_allows_configured_origin_only() -> None:
    client = _client(cors_origins=[ORIGIN])
    allowed = client.get("/healthz", headers={"Origin": ORIGIN})
    denied = client.get("/healthz", headers={"Origin": "https://evil.example"})
    assert allowed.headers["access-control-allow-origin"] == ORIGIN
    assert "access-control-allow-origin" not in denied.headers


def test_cors_preflight_for_configured_origin() -> None:
    client = _client(cors_origins=[ORIGIN])
    response = client.options(
        "/ask",
        headers={
            "Origin": ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == ORIGIN


def test_no_cors_headers_when_no_origins_configured() -> None:
    client = _client()
    response = client.get("/healthz", headers={"Origin": ORIGIN})
    assert "access-control-allow-origin" not in response.headers


def test_wildcard_cors_origin_is_rejected() -> None:
    with pytest.raises(ValueError):
        _client(cors_origins=["*"])


def test_ip_rate_limit_returns_429_with_retry_after() -> None:
    client = _client(max_requests=2)
    assert _ask(client, "u1").status_code == 200
    assert _ask(client, "u2").status_code == 200
    blocked = _ask(client, "u3")
    assert blocked.status_code == 429
    assert blocked.headers["Retry-After"] == "60"


def test_healthz_is_exempt_from_ip_limit() -> None:
    client = _client(max_requests=1)
    _ask(client, "u1")
    assert _ask(client, "u2").status_code == 429
    for _ in range(5):
        assert client.get("/healthz").status_code == 200


def test_spoofed_forwarded_for_from_untrusted_peer_does_not_bypass_limit() -> None:
    client = _client(max_requests=2)
    headers = {"X-Forwarded-For": "1.1.1.1"}
    assert _ask(client, "u1", headers=headers).status_code == 200
    headers = {"X-Forwarded-For": "2.2.2.2"}
    assert _ask(client, "u2", headers=headers).status_code == 200
    headers = {"X-Forwarded-For": "3.3.3.3"}
    assert _ask(client, "u3", headers=headers).status_code == 429


def test_trusted_proxy_forwarded_for_gives_each_client_its_own_bucket() -> None:
    client = _client(
        trusted_proxies=["10.0.0.0/24"], max_requests=1, peer=("10.0.0.1", 50000)
    )
    assert (
        _ask(client, "u1", headers={"X-Forwarded-For": "198.51.100.7"}).status_code
        == 200
    )
    assert (
        _ask(client, "u2", headers={"X-Forwarded-For": "198.51.100.7"}).status_code
        == 429
    )
    assert (
        _ask(client, "u3", headers={"X-Forwarded-For": "198.51.100.8"}).status_code
        == 200
    )
