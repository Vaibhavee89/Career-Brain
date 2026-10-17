import json

import httpx
import pytest

from careerbrain.core.llm import GroqProvider, LLMError
from careerbrain.core.memory import Message

OK_BODY = {"choices": [{"message": {"role": "assistant", "content": "hi there"}}]}


def _provider(handler, sleeps: list[float], **kwargs) -> GroqProvider:
    return GroqProvider(
        "test-key",
        transport=httpx.MockTransport(handler),
        sleep=sleeps.append,
        **kwargs,
    )


def _responses(*items):
    queue = list(items)

    def handler(request: httpx.Request) -> httpx.Response:
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    return handler


def test_returns_content_and_sends_messages_in_order() -> None:
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        assert request.headers["authorization"] == "Bearer test-key"
        return httpx.Response(200, json=OK_BODY)

    provider = _provider(handler, [])
    reply = provider.complete([Message("user", "hello"), Message("assistant", "hey")])

    assert reply == "hi there"
    assert seen[0]["messages"] == [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hey"},
    ]


@pytest.mark.parametrize("status", [429, 500, 502, 503])
def test_retries_retryable_status_then_succeeds(status: int) -> None:
    sleeps: list[float] = []
    handler = _responses(
        httpx.Response(status),
        httpx.Response(status),
        httpx.Response(200, json=OK_BODY),
    )
    provider = _provider(handler, sleeps)

    assert provider.complete([Message("user", "x")]) == "hi there"
    assert sleeps == [1.0, 2.0]


def test_retries_connection_errors_then_succeeds() -> None:
    sleeps: list[float] = []
    handler = _responses(httpx.ConnectError("boom"), httpx.Response(200, json=OK_BODY))
    provider = _provider(handler, sleeps)

    assert provider.complete([Message("user", "x")]) == "hi there"
    assert sleeps == [1.0]


def test_honors_retry_after_header() -> None:
    sleeps: list[float] = []
    handler = _responses(
        httpx.Response(429, headers={"retry-after": "7"}),
        httpx.Response(200, json=OK_BODY),
    )
    provider = _provider(handler, sleeps)

    provider.complete([Message("user", "x")])
    assert sleeps == [7.0]


def test_backoff_is_capped_at_max_delay() -> None:
    sleeps: list[float] = []
    handler = _responses(*[httpx.Response(503)] * 4, httpx.Response(200, json=OK_BODY))
    provider = _provider(handler, sleeps, base_delay=10.0, max_delay=15.0)

    provider.complete([Message("user", "x")])
    assert sleeps == [10.0, 15.0, 15.0, 15.0]


def test_gives_up_after_max_retries() -> None:
    sleeps: list[float] = []
    handler = _responses(*[httpx.Response(500)] * 3)
    provider = _provider(handler, sleeps, max_retries=2)

    with pytest.raises(LLMError):
        provider.complete([Message("user", "x")])
    assert len(sleeps) == 2


def test_connection_error_gives_up_after_max_retries() -> None:
    sleeps: list[float] = []
    handler = _responses(*[httpx.ConnectError("down")] * 3)
    provider = _provider(handler, sleeps, max_retries=2)

    with pytest.raises(LLMError, match="connection failed"):
        provider.complete([Message("user", "x")])


def test_client_error_is_not_retried() -> None:
    sleeps: list[float] = []
    handler = _responses(httpx.Response(400, text="bad request"))
    provider = _provider(handler, sleeps)

    with pytest.raises(LLMError, match="400"):
        provider.complete([Message("user", "x")])
    assert sleeps == []


def test_unexpected_response_shape_raises() -> None:
    handler = _responses(httpx.Response(200, json={"unexpected": True}))
    provider = _provider(handler, [])

    with pytest.raises(LLMError, match="unexpected"):
        provider.complete([Message("user", "x")])


def test_invalid_retry_after_falls_back_to_exponential_backoff() -> None:
    sleeps: list[float] = []
    handler = _responses(
        httpx.Response(429, headers={"retry-after": "soon"}),
        httpx.Response(200, json=OK_BODY),
    )
    provider = _provider(handler, sleeps)

    provider.complete([Message("user", "x")])
    assert sleeps == [1.0]


def test_retry_after_is_capped_at_max_delay() -> None:
    sleeps: list[float] = []
    handler = _responses(
        httpx.Response(429, headers={"retry-after": "600"}),
        httpx.Response(200, json=OK_BODY),
    )
    provider = _provider(handler, sleeps, max_delay=30.0)

    provider.complete([Message("user", "x")])
    assert sleeps == [30.0]


def test_read_timeout_is_retried() -> None:
    sleeps: list[float] = []
    handler = _responses(
        httpx.ReadTimeout("slow"),
        httpx.Response(200, json=OK_BODY),
    )
    provider = _provider(handler, sleeps)

    assert provider.complete([Message("user", "x")]) == "hi there"
    assert sleeps == [1.0]


def test_zero_retries_fails_on_first_retryable_status() -> None:
    sleeps: list[float] = []
    handler = _responses(httpx.Response(429))
    provider = _provider(handler, sleeps, max_retries=0)

    with pytest.raises(LLMError, match="429"):
        provider.complete([Message("user", "x")])
    assert sleeps == []


def test_close_releases_client() -> None:
    provider = _provider(_responses(httpx.Response(200, json=OK_BODY)), [])
    provider.close()
    assert provider._client.is_closed
