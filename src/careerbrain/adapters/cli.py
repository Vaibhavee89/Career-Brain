from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from careerbrain.bootstrap import open_brain
from careerbrain.core.engine import Engine, EngineResult
from careerbrain.core.llm import GroqProvider, LLMError, LLMProvider
from careerbrain.core.memory import Message
from careerbrain.core.ratelimit import CooldownLimiter

CLI_MESSAGE_LIMIT = 4000
COOLDOWN_SECONDS = 1.0
API_KEY_ENV = "GROQ_API_KEY"
LOCAL_USER = "local"
EXIT_COMMANDS = frozenset({"/quit", "/exit"})
SOURCE_PREFIX = "[source: "


class OfflineLLM:
    def complete(self, messages: Sequence[Message]) -> str:
        system = next(m.content for m in messages if m.role == "system")
        headings = [
            line[len(SOURCE_PREFIX) : -1]
            for line in system.splitlines()
            if line.startswith(SOURCE_PREFIX)
        ]
        if not headings:
            return f"Offline demo: no brain pages matched {messages[-1].content!r}."
        pages = "\n".join(f"- {heading}" for heading in headings)
        return f"Offline demo, no LLM call. Pages the answer would draw on:\n{pages}"


def run(
    engine: Engine,
    read: Callable[[str], str],
    write: Callable[[str], None],
) -> None:
    while True:
        try:
            line = read("you> ")
        except (EOFError, KeyboardInterrupt):
            write("")
            return
        text = line.strip()
        if not text:
            continue
        if text.lower() in EXIT_COMMANDS:
            return
        try:
            write(_render(engine.handle(LOCAL_USER, text, CLI_MESSAGE_LIMIT)))
        except LLMError as exc:
            write(f"Language model error: {exc}")


def _render(result: EngineResult) -> str:
    if result.kind == "reset":
        return "History cleared."
    if result.kind == "rate_limited":
        return f"Too fast. Try again in {result.retry_after:.1f}s."
    body = "\n\n".join(result.chunks)
    if result.sources:
        body += f"\n\n(sources: {', '.join(result.sources)})"
    return body


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Chat with the career brain locally.")
    parser.add_argument("--root", type=Path, default=None, help="brain root directory")
    parser.add_argument(
        "--offline",
        action="store_true",
        help="run without calling Groq; lists the pages a reply would use",
    )
    args = parser.parse_args(argv)

    groq: GroqProvider | None = None
    llm: LLMProvider
    if args.offline:
        llm = OfflineLLM()
    else:
        api_key = os.environ.get(API_KEY_ENV)
        if not api_key:
            print(f"Set {API_KEY_ENV} or pass --offline.", file=sys.stderr)
            return 1
        groq = GroqProvider(api_key)
        llm = groq

    try:
        brain = open_brain(args.root)
    except FileNotFoundError as exc:
        print(exc, file=sys.stderr)
        return 1

    engine = Engine(
        retriever=brain,
        llm=llm,
        limiter=CooldownLimiter(COOLDOWN_SECONDS),
    )
    print("Career Brain CLI. Ask a question, /reset to clear history, /quit to exit.")
    try:
        run(engine, input, print)
    finally:
        if groq is not None:
            groq.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
