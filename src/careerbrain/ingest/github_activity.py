from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

import httpx

EVENTS_URL = "https://api.github.com/users/{user}/events/public"
WINS_FILE = "wins.md"


def fetch_public_events(
    user: str, token: str | None, client: httpx.Client
) -> list[dict[str, Any]]:
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    response = client.get(
        EVENTS_URL.format(user=user), params={"per_page": 100}, headers=headers
    )
    response.raise_for_status()
    return response.json()


def merged_pr_lines(events: list[dict[str, Any]], since: dt.date) -> list[str]:
    lines = []
    for event in events:
        if event.get("type") != "PullRequestEvent":
            continue
        payload = event.get("payload", {})
        pr = payload.get("pull_request", {})
        if payload.get("action") != "closed" or not pr.get("merged_at"):
            continue
        merged = dt.date.fromisoformat(pr["merged_at"][:10])
        if merged < since:
            continue
        repo = event["repo"]["name"]
        lines.append(
            f"- {merged.isoformat()} — Merged PR #{pr['number']} in {repo}: "
            f"{pr['title']} (source: {pr['html_url']})"
        )
    return lines


def append_wins(root: Path, lines: list[str]) -> int:
    path = root / WINS_FILE
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    added = [line for line in lines if line.rsplit("(source: ", 1)[-1] not in existing]
    if added:
        separator = "" if existing.endswith("\n") or not existing else "\n"
        path.write_text(
            existing + separator + "\n".join(added) + "\n", encoding="utf-8"
        )
    return len(added)
