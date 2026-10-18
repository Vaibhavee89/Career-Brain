import datetime as dt
import json
from collections.abc import Sequence
from pathlib import Path

import httpx
import pytest

from careerbrain.core.llm import LLMError
from careerbrain.core.memory import Message
from careerbrain.core.retrieval import load_pages
from careerbrain.ingest.__main__ import main as ingest_main
from careerbrain.ingest.generate import (
    build_profile_readme,
    build_resume,
    generate_outputs,
)
from careerbrain.ingest.github_activity import (
    append_wins,
    direct_commit_lines,
    fetch_commits,
    fetch_landed,
    fetch_merged_prs,
    merged_pr_lines,
)
from careerbrain.ingest.inbox import (
    Claim,
    apply_claim,
    parse_claims,
    process_inbox,
)

TODAY = dt.date(2026, 10, 19)


def _write(root: Path, rel: str, text: str) -> None:
    target = root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


def _page(public: str, kind: str, title: str, body: str, extra: str = "") -> str:
    return f"---\ntype: {kind}\npublic: {public}\n{extra}---\n\n# {title}\n\n{body}\n"


@pytest.fixture
def brain(tmp_path: Path) -> Path:
    _write(tmp_path, "brain.config.yaml", "paths: {}\n")
    _write(tmp_path, "wins.md", "# Wins\n\n- 2025-07-08 — Shipped the first thing.\n")
    _write(
        tmp_path,
        "profile/about.md",
        _page(
            "true",
            "profile",
            "About",
            "## Who I am\n<!-- TODO -->\nPrivate draft sentence.\n\n"
            "## 3-line pitch\nI build backend and AI systems.\n\n"
            "## Target roles\n- SDE 1 backend roles\n\n"
            "## Contact\n- Email: me@example.com\n",
        ),
    )
    _write(
        tmp_path,
        "projects/etl.md",
        _page(
            "true",
            "project",
            "ETL Helper",
            "## What it is\nAn agent for DAG failures.\n\n"
            "## Key decisions (and why)\n"
            "- Used MCP servers for Airflow access. Source: CV.\n"
            "- Added OOM diagnostics.\n",
            extra="skills: [python, mcp, airflow]\n",
        ),
    )
    _write(
        tmp_path,
        "projects/cooking.md",
        _page(
            "true",
            "project",
            "Recipe Sorter",
            "## What it is\nSorts recipes.\n\n- Built a CSS grid layout.\n",
            extra="skills: [javascript]\n",
        ),
    )
    _write(
        tmp_path,
        "projects/secret.md",
        _page("false", "project", "Secret Project", "- Confidential metric 42.\n"),
    )
    _write(
        tmp_path,
        "experience/blinkit.md",
        _page(
            "true",
            "experience",
            "Blinkit",
            "- Automated Pinot onboarding. Source: CV.\n",
            extra='company: "Blinkit"\nrole: "SDE Intern"\nstart: 2026-04\nend: 2026-10\n',
        ),
    )
    _write(
        tmp_path,
        "decisions/d.md",
        "---\ntype: decision\npublic: false\n---\n\n## Decision\n\nKeep it.\n",
    )
    return tmp_path


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


def _pr_item(closed_at: str, number: int = 7) -> dict:
    return {
        "number": number,
        "title": "Add cache",
        "html_url": f"https://github.com/owner/repo/pull/{number}",
        "repository_url": "https://api.github.com/repos/owner/repo",
        "closed_at": closed_at,
        "pull_request": {"merged_at": closed_at},
    }


def test_merged_prs_in_window_become_cited_win_lines() -> None:
    items = [
        _pr_item("2026-10-18T10:00:00Z"),
        _pr_item("2026-10-01T10:00:00Z", number=8),
    ]
    lines = merged_pr_lines(items, since=dt.date(2026, 10, 12))
    expected = (
        "- 2026-10-18 — Merged PR #7 in owner/repo: Add cache "
        "(source: https://github.com/owner/repo/pull/7)"
    )
    assert lines == [expected]


def test_fetch_searches_merged_prs_with_token() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("authorization", "")
        seen["q"] = request.url.params.get("q", "")
        return httpx.Response(200, json={"items": [_pr_item("2026-10-18T10:00:00Z")]})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        items = fetch_merged_prs("someone", dt.date(2026, 10, 12), "tok", client)
    assert len(items) == 1
    assert seen["auth"] == "Bearer tok"
    assert seen["q"] == "author:someone is:pr is:merged merged:>=2026-10-12"


def test_append_wins_is_idempotent(brain: Path) -> None:
    lines = merged_pr_lines(
        [_pr_item("2026-10-18T10:00:00Z")], since=dt.date(2026, 10, 1)
    )
    assert append_wins(brain, lines) == 1
    assert append_wins(brain, lines) == 0
    assert (brain / "wins.md").read_text().count("Merged PR #7") == 1


def _commit_item(sha: str, message: str, repo: str = "me/app", day: str = "2026-10-18"):
    return {
        "sha": sha,
        "html_url": f"https://github.com/{repo}/commit/{sha}",
        "commit": {
            "message": message,
            "committer": {"date": f"{day}T10:00:00Z"},
        },
        "repository": {"full_name": repo},
    }


def _github_router(
    pr_numbers_to_commits: dict[int, list[dict]],
    merge_shas: dict[int, str],
    titles: dict[int, str],
):
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/commits"):
            number = int(path.split("/pulls/")[1].split("/")[0])
            return httpx.Response(200, json=pr_numbers_to_commits[number])
        if "/pulls/" in path:
            number = int(path.rsplit("/", 1)[1])
            return httpx.Response(
                200,
                json={
                    "merge_commit_sha": merge_shas[number],
                    "title": titles[number],
                },
            )
        raise AssertionError(f"unexpected request {path}")

    return handler


def test_commit_search_is_scoped_to_user_owned_repos() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["q"] = request.url.params.get("q", "")
        return httpx.Response(200, json={"items": []})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        fetch_commits("me", dt.date(2026, 10, 12), None, client)
    assert seen["q"] == "author:me user:me committer-date:>=2026-10-12"


def test_direct_commits_drop_squash_rebase_and_merge_duplicates() -> None:
    pr_item = {
        "number": 7,
        "title": "Add cache",
        "html_url": "https://github.com/me/app/pull/7",
        "repository_url": "https://api.github.com/repos/me/app",
        "closed_at": "2026-10-18T10:00:00Z",
    }
    handler = _github_router(
        pr_numbers_to_commits={
            7: [
                # rebase-merged: same subject, but a new SHA on main
                {"sha": "aaa111", "commit": {"message": "Wire up LRU cache\n\nbody"}},
            ]
        },
        merge_shas={7: "bbb222"},
        titles={7: "Add cache"},
    )
    commits = [
        _commit_item("bbb222", "Add cache (#7)"),  # squash merge commit
        _commit_item("ccc333", "Wire up LRU cache"),  # rebased copy of PR commit
        _commit_item("ddd444", "Fix typo in README"),  # genuinely direct
    ]
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        landed = fetch_landed([pr_item], "me", None, client)
    lines = direct_commit_lines(commits, dt.date(2026, 10, 12), landed)
    expected = (
        "- 2026-10-18 — Direct commit ddd444 in me/app: Fix typo in README "
        "(source: https://github.com/me/app/commit/ddd444)"
    )
    assert lines == [expected]


def test_prs_in_other_owners_repos_are_not_used_for_dedupe() -> None:
    pr_item = {
        "number": 3,
        "title": "Their change",
        "html_url": "https://github.com/other/lib/pull/3",
        "repository_url": "https://api.github.com/repos/other/lib",
        "closed_at": "2026-10-18T10:00:00Z",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("should not call the API for other owners' PRs")

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        landed = fetch_landed([pr_item], "me", None, client)
    assert landed.shas == set() and landed.subjects == set()


def test_parse_claims_accepts_fenced_json_and_rejects_garbage() -> None:
    raw = '```json\n[{"target": "wins.md", "heading": null, "text": "x"}]\n```'
    assert parse_claims(raw) == [Claim("wins.md", None, "x")]
    assert parse_claims("not json") is None
    assert parse_claims('[{"target": 1}]') is None


def test_claim_must_be_verbatim_from_the_note(brain: Path) -> None:
    note = "Shipped a Kafka consumer last week."
    allowed = {"wins.md"}
    paraphrase = Claim("wins.md", None, "Built a Kafka consumer")
    assert not apply_claim(brain, paraphrase, "inbox/n.md", note, TODAY, allowed)
    verbatim = Claim("wins.md", None, "Shipped a Kafka consumer")
    assert apply_claim(brain, verbatim, "inbox/n.md", note, TODAY, allowed)
    assert (
        "- 2026-10-19 — Shipped a Kafka consumer (source: inbox/n.md)"
        in (brain / "wins.md").read_text()
    )


@pytest.mark.parametrize(
    "target",
    [
        "../outside.md",
        "inbox/n.md",
        "profile/resume-variants/eng.md",
        "projects/missing.md",
    ],
)
def test_claims_cannot_target_outside_the_allow_list(brain: Path, target: str) -> None:
    _write(brain, "outside.md", "x\n")
    note = "Shipped a thing."
    claim = Claim(target, None, "Shipped a thing.")
    assert not apply_claim(brain, claim, "inbox/n.md", note, TODAY, {target})


def test_heading_claim_inserts_under_the_right_section(brain: Path) -> None:
    note = "Chose Groq for latency."
    claim = Claim("decisions/d.md", "Decision", "Chose Groq for latency.")
    assert apply_claim(brain, claim, "inbox/n.md", note, TODAY, {"decisions/d.md"})
    text = (brain / "decisions/d.md").read_text()
    assert text.index("## Decision") < text.index("- Chose Groq for latency.")
    assert text.endswith("- Chose Groq for latency. (source: inbox/n.md)\n")


def test_unknown_heading_is_rejected(brain: Path) -> None:
    claim = Claim("decisions/d.md", "Nope", "Keep it.")
    assert not apply_claim(
        brain, claim, "inbox/n.md", "Keep it.", TODAY, {"decisions/d.md"}
    )


def test_process_inbox_removes_fully_applied_notes_and_keeps_rejected_ones(
    brain: Path,
) -> None:
    _write(brain, "inbox/a-good.md", "Shipped a Kafka consumer last week.\n")
    _write(brain, "inbox/b-bad.md", "Something the model invented.\n")
    good = json.dumps(
        [{"target": "wins.md", "heading": None, "text": "Shipped a Kafka consumer"}]
    )
    bad = json.dumps(
        [{"target": "wins.md", "heading": None, "text": "Hallucinated claim"}]
    )
    llm = FakeLLM([good, bad])

    report = process_inbox(brain, llm, TODAY)

    assert report.notes == 2
    assert report.applied == 1
    assert report.rejected == 1
    assert report.removed == 1
    assert not (brain / "inbox/a-good.md").exists()
    assert (brain / "inbox/b-bad.md").exists()


def test_process_inbox_keeps_note_when_llm_fails(brain: Path) -> None:
    _write(brain, "inbox/note.md", "Shipped a thing.\n")
    report = process_inbox(brain, FakeLLM([LLMError("down")]), TODAY)
    assert report.unparseable == 1
    assert (brain / "inbox/note.md").exists()


def test_eng_resume_uses_only_public_pages_and_strips_citations(brain: Path) -> None:
    pages = load_pages(brain)
    resume = build_resume([p for p in pages if p.is_public], "eng", TODAY)
    assert "public: true" in resume
    assert "Used MCP servers for Airflow access." in resume
    assert "Source:" not in resume
    assert "Confidential" not in resume
    assert "Secret Project" not in resume


def test_ai_resume_keeps_only_ai_tagged_projects(brain: Path) -> None:
    pages = [p for p in load_pages(brain) if p.is_public]
    resume = build_resume(pages, "ai-eng", TODAY)
    assert "ETL Helper" in resume
    assert "Recipe Sorter" not in resume


def test_resume_without_public_entries_is_marked_not_public(brain: Path) -> None:
    resume = build_resume([], "eng", TODAY)
    assert "public: false" in resume
    assert "No public entries yet." in resume


def test_profile_readme_has_public_sections_only(brain: Path) -> None:
    readme = build_profile_readme([p for p in load_pages(brain) if p.is_public])
    assert "I build backend and AI systems." in readme
    assert "- SDE 1 backend roles" in readme
    assert "**ETL Helper**" in readme
    assert "**Blinkit** — SDE Intern" in readme
    assert "Private draft sentence." not in readme
    assert "TODO" not in readme
    assert "Secret Project" not in readme


def test_generate_outputs_writes_expected_files(brain: Path) -> None:
    written = generate_outputs(brain, load_pages(brain), TODAY)
    assert written == [
        "profile/resume-variants/eng.md",
        "profile/resume-variants/ai-eng.md",
        "generated/profile-README.md",
    ]
    assert (brain / "generated/profile-README.md").is_file()


def test_cli_runs_without_github_or_llm(
    brain: Path, tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    summary = tmp_path / "summary.md"
    assert (
        ingest_main(["--root", str(brain), "--skip-github", "--summary", str(summary)])
        == 0
    )
    assert "Inbox: skipped" in summary.read_text()
    assert (brain / "profile/resume-variants/eng.md").is_file()
