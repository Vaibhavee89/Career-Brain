from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from slack_sdk import WebClient

from careerbrain.adapters.common import (
    SLACK_MESSAGE_LIMIT,
    InboundMessage,
    RecentEvents,
    build_engine,
    dispatch,
    strip_mentions,
    truncate_inbound,
)
from careerbrain.core.engine import Engine

PLATFORM = "slack"
BOT_TOKEN_ENV = "SLACK_BOT_TOKEN"
APP_TOKEN_ENV = "SLACK_APP_TOKEN"
RESET_TEXT = "/reset"
ASK_COMMAND = "/ask"
RESET_COMMAND = "/reset"


def translate_mention(event: dict[str, Any], bot_user_id: str) -> InboundMessage | None:
    if event.get("bot_id") or event.get("subtype"):
        return None
    channel = event["channel"]
    thread = event.get("thread_ts") or event["ts"]
    user_id = f"{PLATFORM}:{event.get('user', 'unknown')}"
    conversation_key = f"{PLATFORM}:{channel}:{thread}"
    text = strip_mentions(event.get("text", ""), [bot_user_id])
    if text.lower().startswith(RESET_TEXT):
        return InboundMessage(PLATFORM, user_id, conversation_key, "", kind="reset")
    text = truncate_inbound(text)
    if not text:
        return None
    return InboundMessage(PLATFORM, user_id, conversation_key, text)


def translate_slash(command: dict[str, Any]) -> InboundMessage | None:
    user_id = f"{PLATFORM}:{command['user_id']}"
    conversation_key = f"{PLATFORM}:{command['channel_id']}"
    if command["command"] == RESET_COMMAND:
        return InboundMessage(PLATFORM, user_id, conversation_key, "", kind="reset")
    text = truncate_inbound(command.get("text", "").strip())
    if not text:
        return None
    return InboundMessage(PLATFORM, user_id, conversation_key, text)


def build_app(
    engine: Engine,
    bot_user_id: str,
    bot_token: str,
    recent_events: RecentEvents | None = None,
) -> App:
    app = App(token=bot_token)
    seen = recent_events or RecentEvents()

    @app.event("app_mention")
    def on_mention(
        event: dict[str, Any], body: dict[str, Any], say: Callable[..., Any]
    ) -> None:
        if seen.check_and_add(body["event_id"]):
            return
        inbound = translate_mention(event, bot_user_id)
        if inbound is None:
            return
        thread = event.get("thread_ts") or event["ts"]
        for chunk in dispatch(engine, inbound, PLATFORM, SLACK_MESSAGE_LIMIT):
            say(text=chunk, thread_ts=thread)

    def on_command(
        ack: Callable[[], None], command: dict[str, Any], client: Any
    ) -> None:
        ack()
        inbound = translate_slash(command)
        if inbound is None:
            client.chat_postEphemeral(
                channel=command["channel_id"],
                user=command["user_id"],
                text=f"Usage: {ASK_COMMAND} <question>",
            )
            return
        for chunk in dispatch(engine, inbound, PLATFORM, SLACK_MESSAGE_LIMIT):
            client.chat_postMessage(channel=command["channel_id"], text=chunk)

    app.command(ASK_COMMAND)(on_command)
    app.command(RESET_COMMAND)(on_command)
    return app


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the career brain Slack bot.")
    parser.add_argument("--root", type=Path, default=None, help="brain root directory")
    parser.add_argument(
        "--offline",
        action="store_true",
        help="run without calling Groq; lists the pages a reply would use",
    )
    args = parser.parse_args(argv)

    bot_token = os.environ.get(BOT_TOKEN_ENV)
    app_token = os.environ.get(APP_TOKEN_ENV)
    if not bot_token or not app_token:
        print(f"Set {BOT_TOKEN_ENV} and {APP_TOKEN_ENV}.", file=sys.stderr)
        return 1
    try:
        engine = build_engine(args.root, args.offline)
    except (RuntimeError, FileNotFoundError) as exc:
        print(exc, file=sys.stderr)
        return 1

    bot_user_id = WebClient(token=bot_token).auth_test()["user_id"]
    app = build_app(engine, bot_user_id, bot_token)
    SocketModeHandler(app, app_token).start()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
