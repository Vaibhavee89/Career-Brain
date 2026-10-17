from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import discord
from discord import app_commands

from careerbrain.adapters.common import (
    DISCORD_MESSAGE_LIMIT,
    InboundMessage,
    build_engine,
    dispatch,
    strip_mentions,
    truncate_inbound,
)
from careerbrain.core.engine import Engine
from careerbrain.core.llm import DEFAULT_MODEL

PLATFORM = "discord"
TOKEN_ENV = "DISCORD_BOT_TOKEN"
RESET_PREFIX = "!reset"


def translate_message(message: Any, bot_id: str) -> InboundMessage | None:
    if message.author.bot:
        return None
    user_id = f"{PLATFORM}:{message.author.id}"
    conversation_key = f"{PLATFORM}:{message.channel.id}"
    content = message.content.strip()
    if content.lower().startswith(RESET_PREFIX):
        return InboundMessage(PLATFORM, user_id, conversation_key, "", kind="reset")
    is_dm = message.guild is None
    mentioned = any(str(user.id) == bot_id for user in message.mentions)
    if not (is_dm or mentioned):
        return None
    text = truncate_inbound(strip_mentions(content, [bot_id]))
    if not text:
        return None
    return InboundMessage(PLATFORM, user_id, conversation_key, text)


class CareerBrainClient(discord.Client):
    def __init__(self, engine: Engine, model_name: str) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents)
        self._engine = engine
        self._model_name = model_name
        self.tree = app_commands.CommandTree(self)
        self._register_commands()

    async def setup_hook(self) -> None:
        await self.tree.sync()

    async def on_message(self, message: discord.Message) -> None:
        if self.user is None:
            return
        inbound = translate_message(message, str(self.user.id))
        if inbound is None:
            return
        chunks = await asyncio.to_thread(
            dispatch, self._engine, inbound, PLATFORM, DISCORD_MESSAGE_LIMIT
        )
        for chunk in chunks:
            await message.reply(chunk, mention_author=False)

    def _register_commands(self) -> None:
        @self.tree.command(
            name="ask", description="Ask a question about the career brain"
        )
        @app_commands.describe(question="What do you want to know?")
        async def ask(interaction: discord.Interaction, question: str) -> None:
            await interaction.response.defer(thinking=True)
            inbound = InboundMessage(
                PLATFORM,
                f"{PLATFORM}:{interaction.user.id}",
                f"{PLATFORM}:{interaction.channel_id}",
                truncate_inbound(question.strip()),
            )
            chunks = await asyncio.to_thread(
                dispatch, self._engine, inbound, PLATFORM, DISCORD_MESSAGE_LIMIT
            )
            for chunk in chunks:
                await interaction.followup.send(chunk)

        @self.tree.command(
            name="reset", description="Clear this channel's conversation history"
        )
        async def reset(interaction: discord.Interaction) -> None:
            inbound = InboundMessage(
                PLATFORM,
                f"{PLATFORM}:{interaction.user.id}",
                f"{PLATFORM}:{interaction.channel_id}",
                "",
                kind="reset",
            )
            chunks = dispatch(self._engine, inbound, PLATFORM, DISCORD_MESSAGE_LIMIT)
            await interaction.response.send_message(chunks[0], ephemeral=True)

        @self.tree.command(
            name="model", description="Show the model answering questions"
        )
        async def model(interaction: discord.Interaction) -> None:
            await interaction.response.send_message(
                f"Model: {self._model_name}", ephemeral=True
            )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the career brain Discord bot.")
    parser.add_argument("--root", type=Path, default=None, help="brain root directory")
    parser.add_argument(
        "--offline",
        action="store_true",
        help="run without calling Groq; lists the pages a reply would use",
    )
    args = parser.parse_args(argv)

    token = os.environ.get(TOKEN_ENV)
    if not token:
        print(f"Set {TOKEN_ENV}.", file=sys.stderr)
        return 1
    try:
        engine = build_engine(args.root, args.offline)
    except (RuntimeError, FileNotFoundError) as exc:
        print(exc, file=sys.stderr)
        return 1

    model_name = "offline" if args.offline else DEFAULT_MODEL
    CareerBrainClient(engine, model_name).run(token)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
