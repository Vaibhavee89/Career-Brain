from collections.abc import Sequence
from pathlib import Path
from types import SimpleNamespace

import pytest

from careerbrain.adapters import common, discord_bot, slack_bot
from careerbrain.adapters.common import (
    DISCORD_MESSAGE_LIMIT,
    LLM_UNAVAILABLE_TEXT,
    SLACK_MESSAGE_LIMIT,
    InboundMessage,
    RecentEvents,
    build_engine,
    dispatch,
    render_reply,
    strip_mentions,
    to_slack_mrkdwn,
)
from careerbrain.core.engine import Engine
from careerbrain.core.llm import LLMError
from careerbrain.core.memory import Message
from careerbrain.core.ratelimit import CooldownLimiter
from careerbrain.core.types import Page, SearchResult

BOT_SLACK = "UBOT"
BOT_DISCORD = "555"


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


class FakeRetriever:
    def search(self, query: str, limit: int = 5) -> list[SearchResult]:
        page = Page(path="projects/etl.md", frontmatter={"public": "true"}, body="etl")
        return [SearchResult(page=page, score=1, snippet="etl")]


class FakeLLM:
    def __init__(self, replies: Sequence[str | Exception]) -> None:
        self._replies = list(replies)
        self.calls: list[list[Message]] = []

    def complete(self, messages: Sequence[Message]) -> str:
        self.calls.append(list(messages))
        item = self._replies.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _engine(llm: FakeLLM, clock: FakeClock | None = None) -> Engine:
    return Engine(
        retriever=FakeRetriever(),
        llm=llm,
        limiter=CooldownLimiter(10.0, clock=clock or FakeClock()),
    )


def _discord_message(
    content: str,
    *,
    author_id: int = 42,
    bot: bool = False,
    guild: bool = True,
    mentions: Sequence[int] = (),
    channel_id: int = 900,
) -> SimpleNamespace:
    return SimpleNamespace(
        author=SimpleNamespace(id=author_id, bot=bot),
        channel=SimpleNamespace(id=channel_id),
        guild=SimpleNamespace(id=1) if guild else None,
        mentions=[SimpleNamespace(id=uid) for uid in mentions],
        content=content,
    )


# Slack contract: platform event in, InboundMessage out.


def test_slack_top_level_mention_keys_by_channel_and_message_ts() -> None:
    event = {
        "channel": "C1",
        "ts": "1700.1",
        "user": "U9",
        "text": f"<@{BOT_SLACK}> what did you build?",
    }
    assert slack_bot.translate_mention(event, BOT_SLACK) == InboundMessage(
        platform="slack",
        user_id="slack:U9",
        conversation_key="slack:C1:1700.1",
        text="what did you build?",
    )


def test_slack_thread_reply_keys_by_thread_root() -> None:
    event = {
        "channel": "C1",
        "ts": "1700.2",
        "thread_ts": "1700.1",
        "user": "U9",
        "text": f"<@{BOT_SLACK}> and before that?",
    }
    message = slack_bot.translate_mention(event, BOT_SLACK)
    assert message is not None
    assert message.conversation_key == "slack:C1:1700.1"


def test_slack_bot_authored_and_edited_events_are_ignored() -> None:
    base = {"channel": "C1", "ts": "1", "text": f"<@{BOT_SLACK}> hi"}
    assert slack_bot.translate_mention({**base, "bot_id": "B1"}, BOT_SLACK) is None
    assert (
        slack_bot.translate_mention({**base, "subtype": "message_changed"}, BOT_SLACK)
        is None
    )


def test_slack_mention_with_no_text_is_ignored() -> None:
    event = {"channel": "C1", "ts": "1", "user": "U9", "text": f"<@{BOT_SLACK}>"}
    assert slack_bot.translate_mention(event, BOT_SLACK) is None


def test_slack_mention_reset_is_a_reset_for_that_thread() -> None:
    event = {
        "channel": "C1",
        "ts": "1700.3",
        "thread_ts": "1700.1",
        "user": "U9",
        "text": f"<@{BOT_SLACK}> /reset",
    }
    assert slack_bot.translate_mention(event, BOT_SLACK) == InboundMessage(
        platform="slack",
        user_id="slack:U9",
        conversation_key="slack:C1:1700.1",
        text="",
        kind="reset",
    )


def test_slack_ask_slash_command_keys_by_channel_only() -> None:
    command = {
        "command": "/ask",
        "text": "  what is your stack? ",
        "channel_id": "C1",
        "user_id": "U9",
    }
    assert slack_bot.translate_slash(command) == InboundMessage(
        platform="slack",
        user_id="slack:U9",
        conversation_key="slack:C1",
        text="what is your stack?",
    )


def test_slack_reset_slash_command_is_channel_scoped_reset() -> None:
    command = {"command": "/reset", "text": "", "channel_id": "C1", "user_id": "U9"}
    message = slack_bot.translate_slash(command)
    assert message is not None
    assert message.kind == "reset"
    assert message.conversation_key == "slack:C1"


def test_slack_empty_ask_is_rejected() -> None:
    command = {"command": "/ask", "text": "  ", "channel_id": "C1", "user_id": "U9"}
    assert slack_bot.translate_slash(command) is None


# Discord contract: platform event in, InboundMessage out.


def test_discord_guild_mention_strips_bot_mention_and_keys_by_channel() -> None:
    message = _discord_message(
        f"<@!{BOT_DISCORD}> tell me about Airflow", mentions=[int(BOT_DISCORD)]
    )
    assert discord_bot.translate_message(message, BOT_DISCORD) == InboundMessage(
        platform="discord",
        user_id="discord:42",
        conversation_key="discord:900",
        text="tell me about Airflow",
    )


def test_discord_guild_message_without_mention_is_ignored() -> None:
    message = _discord_message("just chatting")
    assert discord_bot.translate_message(message, BOT_DISCORD) is None


def test_discord_direct_message_needs_no_mention() -> None:
    message = _discord_message("hello there", guild=False)
    result = discord_bot.translate_message(message, BOT_DISCORD)
    assert result is not None
    assert result.text == "hello there"


def test_discord_bang_reset_is_a_reset() -> None:
    message = _discord_message("!reset", guild=False)
    assert discord_bot.translate_message(message, BOT_DISCORD) == InboundMessage(
        platform="discord",
        user_id="discord:42",
        conversation_key="discord:900",
        text="",
        kind="reset",
    )


def test_discord_bot_authors_are_ignored() -> None:
    message = _discord_message("!reset", bot=True)
    assert discord_bot.translate_message(message, BOT_DISCORD) is None


# Common helpers.


@pytest.mark.parametrize(
    ("text", "bot_ids", "expected"),
    [
        ("<@UBOT> hi <@UOTHER>", ["UBOT"], "hi <@UOTHER>"),
        ("<@!555>   spaced   out", ["555"], "spaced out"),
        ("no mention here", ["555"], "no mention here"),
    ],
)
def test_strip_mentions(text: str, bot_ids: list[str], expected: str) -> None:
    assert strip_mentions(text, bot_ids) == expected


@pytest.mark.parametrize(
    ("markdown", "expected"),
    [
        ("**bold** and __also__", "*bold* and *also*"),
        ("*italic* text", "_italic_ text"),
        ("~~gone~~", "~gone~"),
        ("[site](https://example.com/a?b=1)", "<https://example.com/a?b=1|site>"),
        ("# Heading", "*Heading*"),
        ("a < b & c > d", "a &lt; b &amp; c &gt; d"),
    ],
)
def test_slack_mrkdwn_conversion(markdown: str, expected: str) -> None:
    assert to_slack_mrkdwn(markdown) == expected


def test_slack_mrkdwn_leaves_code_blocks_alone() -> None:
    text = "**out**\n```\n**keep** & <this>\n```\n*x*"
    assert to_slack_mrkdwn(text) == "*out*\n```\n**keep** & <this>\n```\n_x_"


@pytest.mark.parametrize(("platform", "limit"), [("slack", 50), ("discord", 50)])
def test_rendered_chunks_respect_platform_limit(platform: str, limit: int) -> None:
    text = " ".join(["word"] * 200)
    chunks = render_reply(text, platform, limit)
    assert len(chunks) > 1
    assert all(len(chunk) <= limit for chunk in chunks)


def test_platform_limits_are_documented_values() -> None:
    assert DISCORD_MESSAGE_LIMIT == 2_000
    assert SLACK_MESSAGE_LIMIT == 40_000


def test_recent_events_suppresses_repeats_until_ttl() -> None:
    clock = FakeClock()
    recent = RecentEvents(ttl=300.0, clock=clock)
    assert recent.check_and_add("Ev1") is False
    assert recent.check_and_add("Ev1") is True
    clock.now = 299.0
    assert recent.check_and_add("Ev1") is True
    clock.now = 301.0
    assert recent.check_and_add("Ev1") is False


def test_recent_events_evicts_oldest_when_full() -> None:
    recent = RecentEvents(max_size=2, clock=FakeClock())
    recent.check_and_add("a")
    recent.check_and_add("b")
    recent.check_and_add("c")
    assert recent.check_and_add("a") is False
    assert recent.check_and_add("c") is True


def test_reset_message_clears_only_its_conversation() -> None:
    llm = FakeLLM(["first", "second", "third"])
    clock = FakeClock()
    engine = _engine(llm, clock)

    def send(conversation: str, text: str, kind: str = "message") -> list[str]:
        clock.now += 60.0
        return dispatch(
            engine,
            InboundMessage("slack", "slack:U1", conversation, text, kind=kind),
            "slack",
            SLACK_MESSAGE_LIMIT,
        )

    send("slack:C1:1", "one")
    send("slack:C1:2", "other")
    assert send("slack:C1:1", "", kind="reset") == ["History cleared."]
    send("slack:C1:1", "two")
    assert [m.content for m in llm.calls[2][1:]] == ["two"]


def test_rate_limit_follows_user_across_conversations() -> None:
    clock = FakeClock()
    engine = _engine(FakeLLM(["first"]), clock)
    dispatch(
        engine,
        InboundMessage("slack", "slack:U1", "slack:C1:1", "one"),
        "slack",
        SLACK_MESSAGE_LIMIT,
    )
    (blocked,) = dispatch(
        engine,
        InboundMessage("slack", "slack:U1", "slack:C1:2", "two"),
        "slack",
        SLACK_MESSAGE_LIMIT,
    )
    assert blocked.startswith("Too fast.")


# build_engine: Discord/Slack should get the same retrieval wiring as the HTTP API.


@pytest.fixture
def brain_root(tmp_path: Path) -> Path:
    (tmp_path / "brain.config.yaml").write_text("paths: {}\n", encoding="utf-8")
    (tmp_path / "projects").mkdir()
    (tmp_path / "projects/etl.md").write_text(
        '---\npublic: "true"\n---\n# ETL\n\nbuilt an ETL agent\n', encoding="utf-8"
    )
    return tmp_path


def test_build_engine_wires_pinecone_vectors_into_the_retriever(
    brain_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sentinel = object()
    monkeypatch.setenv("GROQ_API_KEY", "key")
    monkeypatch.setattr(common, "sync_vectors", lambda brain: sentinel)

    engine = build_engine(brain_root, offline=False)

    assert engine._retriever._vectors is sentinel  # type: ignore[attr-defined]


def test_build_engine_skips_vector_sync_when_offline(
    brain_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[object] = []
    monkeypatch.setattr(common, "sync_vectors", lambda brain: calls.append(brain))

    engine = build_engine(brain_root, offline=True)

    assert calls == []
    assert engine._retriever._vectors is None  # type: ignore[attr-defined]


def test_llm_failure_returns_friendly_text_instead_of_raising() -> None:
    engine = _engine(FakeLLM([LLMError("upstream secret")]))
    chunks = dispatch(
        engine,
        InboundMessage("discord", "discord:42", "discord:900", "hi"),
        "discord",
        DISCORD_MESSAGE_LIMIT,
    )
    assert chunks == [LLM_UNAVAILABLE_TEXT]
    assert "secret" not in chunks[0]
