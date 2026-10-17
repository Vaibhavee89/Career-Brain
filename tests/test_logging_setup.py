import io
import json
import logging

import pytest

from careerbrain.core.logging_setup import configure_logging, hash_id

KEY = b"test-key"


@pytest.fixture
def stream() -> io.StringIO:
    buffer = io.StringIO()
    configure_logging("DEBUG", stream=buffer)
    yield buffer
    for handler in list(logging.getLogger().handlers):
        if handler.get_name() == "careerbrain-json":
            logging.getLogger().removeHandler(handler)


def _last_record(stream: io.StringIO) -> dict:
    return json.loads(stream.getvalue().strip().splitlines()[-1])


def test_emits_json_with_standard_fields(stream: io.StringIO) -> None:
    logging.getLogger("test").info("hello")
    record = _last_record(stream)
    assert record["level"] == "INFO"
    assert record["logger"] == "test"
    assert record["message"] == "hello"
    assert "ts" in record


def test_includes_latency_tokens_retries_and_hashed_user(stream: io.StringIO) -> None:
    logging.getLogger("test").info(
        "llm call",
        extra={
            "event": "llm_call",
            "latency_ms": 412.5,
            "tokens": 830,
            "retries": 2,
            "user_hash": hash_id("123456789", KEY),
        },
    )
    record = _last_record(stream)
    assert record["event"] == "llm_call"
    assert record["latency_ms"] == 412.5
    assert record["tokens"] == 830
    assert record["retries"] == 2
    assert record["user_hash"] == hash_id("123456789", KEY)


def test_raw_ids_are_never_emitted(stream: io.StringIO) -> None:
    logging.getLogger("test").info("hi", extra={"user_id": "123456789"})
    assert "123456789" not in stream.getvalue()
    assert "user_id" not in _last_record(stream)


def test_exception_info_is_included(stream: io.StringIO) -> None:
    try:
        raise RuntimeError("boom")
    except RuntimeError:
        logging.getLogger("test").exception("failed")
    assert "RuntimeError: boom" in _last_record(stream)["exception"]


def test_hash_id_is_stable_and_keyed() -> None:
    assert hash_id("42", KEY) == hash_id("42", KEY)
    assert hash_id("42", KEY) != hash_id("42", b"other-key")
    assert hash_id("42", KEY) != "42"
    assert len(hash_id("42", KEY)) == 16


def test_configure_twice_does_not_duplicate_output() -> None:
    first = io.StringIO()
    second = io.StringIO()
    configure_logging("INFO", stream=first)
    configure_logging("INFO", stream=second)
    logging.getLogger("test").info("once")
    assert first.getvalue() == ""
    assert len(second.getvalue().strip().splitlines()) == 1
    for handler in list(logging.getLogger().handlers):
        if handler.get_name() == "careerbrain-json":
            logging.getLogger().removeHandler(handler)
