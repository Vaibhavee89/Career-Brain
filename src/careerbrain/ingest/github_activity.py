from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

API = "https://api.github.com"
SEARCH_ISSUES_URL = f"{API}/search/issues"
SEARCH_COMMITS_URL = f"{API}/search/commits"
WINS_FILE = "wins.md"


@dataclass
class Landed:
    """Commits that reached a repo's default branch through a merged PR."""

    shas: set[tuple[str, str]] = field(default_factory=set)  # (repo, sha)
    subjects: set[tuple[str, str]] = field(default_factory=set)  # (repo, subject)


def _headers(token: str | None) -> dict[str, str]:
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _repo_of(item: dict[str, Any]) -> str:
    return item["repository_url"].split("/repos/", 1)[1]


def _subject(message: str) -> str:
    return message.splitlines()[0].strip() if message.strip() else ""


def fetch_merged_prs(
    user: str, since: dt.date, token: str | None, client: httpx.Client
) -> list[dict[str, Any]]:
    query = f"author:{user} is:pr is:merged merged:>={since.isoformat()}"
    response = client.get(
        SEARCH_ISSUES_URL,
        params={"q": query, "per_page": 100},
        headers=_headers(token),
    )
    response.raise_for_status()
    return response.json().get("items", [])


def fetch_commits(
    user: str, since: dt.date, token: str | None, client: httpx.Client
) -> list[dict[str, Any]]:
    # user: limits the search to repos owned by the user, so other people's
    # repos stay out of the brain.
    query = f"author:{user} user:{user} committer-date:>={since.isoformat()}"
    response = client.get(
        SEARCH_COMMITS_URL,
        params={"q": query, "per_page": 100},
        headers=_headers(token),
    )
    response.raise_for_status()
    return response.json().get("items", [])


def fetch_landed(
    merged_prs: list[dict[str, Any]],
    user: str,
    token: str | None,
    client: httpx.Client,
) -> Landed:
    """Map every commit that merged PRs put on the default branch.

    Covers squash and merge commits (merge_commit_sha) and the PR's own commits,
    which rebase merges copy over with new SHAs but the same subject line.
    """
    landed = Landed()
    for item in merged_prs:
        repo = _repo_of(item)
        if repo.split("/")[0].lower() != user.lower():
            continue
        number = item["number"]
        pr = client.get(f"{API}/repos/{repo}/pulls/{number}", headers=_headers(token))
        pr.raise_for_status()
        pr_data = pr.json()
        if pr_data.get("merge_commit_sha"):
            landed.shas.add((repo, pr_data["merge_commit_sha"]))
        landed.subjects.add((repo, pr_data["title"].strip()))

        commits = client.get(
            f"{API}/repos/{repo}/pulls/{number}/commits",
            params={"per_page": 100},
            headers=_headers(token),
        )
        commits.raise_for_status()
        for commit in commits.json():
            landed.shas.add((repo, commit["sha"]))
            landed.subjects.add((repo, _subject(commit["commit"]["message"])))
    return landed


def drop_landed(commits: list[dict[str, Any]], landed: Landed) -> list[dict[str, Any]]:
    kept = []
    for commit in commits:
        repo = commit["repository"]["full_name"]
        subject = _subject(commit["commit"]["message"])
        if (repo, commit["sha"]) in landed.shas or (repo, subject) in landed.subjects:
            continue
        kept.append(commit)
    return kept


def merged_pr_lines(items: list[dict[str, Any]], since: dt.date) -> list[str]:
    lines = []
    for item in items:
        merged = dt.date.fromisoformat(item["closed_at"][:10])
        if merged < since:
            continue
        lines.append(
            f"- {merged.isoformat()} — Merged PR #{item['number']} in {_repo_of(item)}: "
            f"{item['title']} (source: {item['html_url']})"
        )
    return lines


def direct_commit_lines(
    commits: list[dict[str, Any]], since: dt.date, landed: Landed
) -> list[str]:
    lines = []
    for commit in drop_landed(commits, landed):
        committed = dt.date.fromisoformat(commit["commit"]["committer"]["date"][:10])
        if committed < since:
            continue
        repo = commit["repository"]["full_name"]
        subject = _subject(commit["commit"]["message"])
        lines.append(
            f"- {committed.isoformat()} — Direct commit {commit['sha'][:7]} in {repo}: "
            f"{subject} (source: {commit['html_url']})"
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
