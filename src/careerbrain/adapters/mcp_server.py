from __future__ import annotations

import argparse
import re
from collections.abc import Sequence
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from careerbrain.bootstrap import Brain, open_brain
from careerbrain.core.types import Page, PathTraversalError

SERVER_NAME = "careerbrain"
DEFAULT_LIMIT = 5
MAX_LIMIT = 20
DEFAULT_WINS = 10
MAX_WINS = 50
DEFAULT_RESUME = "eng"
RESUME_DIR = "profile/resume-variants"
NOT_FOUND = {"error": "not found"}
WINS_PATH_KEY = "wins"
WIN_LINE = re.compile(r"^- (\d{4}-\d{2}-\d{2}) — (.+)$")
VARIANT_NAME = re.compile(r"[a-z0-9-]+")


def search_brain(brain: Brain, query: str, limit: int = DEFAULT_LIMIT) -> list[dict]:
    limit = max(1, min(limit, MAX_LIMIT))
    return [
        {"path": result.page.path, "score": result.score, "snippet": result.snippet}
        for result in brain.search(query, limit=limit)
    ]


def get_page(brain: Brain, path: str) -> dict[str, str]:
    page = _public_page(brain, path)
    if page is None:
        return dict(NOT_FOUND)
    return {"path": page.path, "body": page.body}


def get_resume(brain: Brain, variant: str = DEFAULT_RESUME) -> dict[str, str]:
    if not VARIANT_NAME.fullmatch(variant):
        return dict(NOT_FOUND)
    return get_page(brain, f"{RESUME_DIR}/{variant}.md")


def recent_wins(brain: Brain, limit: int = DEFAULT_WINS) -> list[dict[str, str]]:
    limit = max(1, min(limit, MAX_WINS))
    page = _public_page(brain, brain.config.paths.get(WINS_PATH_KEY, "wins.md"))
    if page is None:
        return []
    wins = [
        {"date": match.group(1), "text": match.group(2)}
        for match in map(WIN_LINE.match, page.body.splitlines())
        if match
    ]
    wins.sort(key=lambda win: win["date"], reverse=True)
    return wins[:limit]


def _public_page(brain: Brain, path: str) -> Page | None:
    try:
        return brain.get_page(path)
    except PathTraversalError:
        return None


def build_server(brain: Brain) -> FastMCP:
    server = FastMCP(SERVER_NAME)

    @server.tool(
        name="search_brain",
        description="Keyword search over public career pages. Returns paths and snippets.",
    )
    def _search_brain(query: str, limit: int = DEFAULT_LIMIT) -> list[dict]:
        return search_brain(brain, query, limit)

    @server.tool(
        name="get_page",
        description="Return the full text of a public career page by its relative path.",
    )
    def _get_page(path: str) -> dict[str, str]:
        return get_page(brain, path)

    @server.tool(
        name="get_resume",
        description="Return a public resume variant (e.g. 'eng' or 'ai-eng').",
    )
    def _get_resume(variant: str = DEFAULT_RESUME) -> dict[str, str]:
        return get_resume(brain, variant)

    @server.tool(
        name="recent_wins",
        description="Return the most recent dated wins, newest first. Empty if wins are not public.",
    )
    def _recent_wins(limit: int = DEFAULT_WINS) -> list[dict[str, str]]:
        return recent_wins(brain, limit)

    return server


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Serve public career brain pages over MCP."
    )
    parser.add_argument("--root", type=Path, default=None, help="brain root directory")
    args = parser.parse_args(argv)
    build_server(open_brain(args.root)).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
