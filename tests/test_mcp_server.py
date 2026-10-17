import asyncio
from pathlib import Path

import pytest

from careerbrain.adapters.mcp_server import (
    MAX_LIMIT,
    build_server,
    get_page,
    get_resume,
    recent_wins,
    search_brain,
)
from careerbrain.bootstrap import open_brain


def _write(root: Path, rel: str, public: str, body: str) -> None:
    target = root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        f"---\ntype: project\npublic: {public}\n---\n\n# {rel}\n\n{body}\n",
        encoding="utf-8",
    )


@pytest.fixture
def brain(tmp_path: Path):
    (tmp_path / "brain.config.yaml").write_text("paths: {}\n", encoding="utf-8")
    _write(tmp_path, "projects/public.md", "true", "airflow triage agent")
    _write(tmp_path, "decisions/secret.md", "false", "airflow salary notes")
    _write(tmp_path, "profile/unflagged.md", "maybe", "airflow private draft")
    (tmp_path.parent / "outside-secret.env").write_text("KEY=1\n", encoding="utf-8")
    return open_brain(tmp_path)


def test_search_returns_only_public_pages(brain) -> None:
    paths = [hit["path"] for hit in search_brain(brain, "airflow")]
    assert paths == ["projects/public.md"]


def test_search_result_shape(brain) -> None:
    (hit,) = search_brain(brain, "triage")
    assert set(hit) == {"path", "score", "snippet"}
    assert hit["snippet"] == "airflow triage agent"


def test_search_clamps_limit(brain, tmp_path: Path) -> None:
    for index in range(MAX_LIMIT + 5):
        _write(tmp_path, f"projects/extra-{index}.md", "true", "shared term")
    assert len(search_brain(brain, "shared", limit=10_000)) == MAX_LIMIT
    assert len(search_brain(brain, "shared", limit=0)) == 1


def test_get_page_returns_public_body(brain) -> None:
    page = get_page(brain, "projects/public.md")
    assert page["path"] == "projects/public.md"
    assert "airflow triage agent" in page["body"]
    assert "public:" not in page["body"]


@pytest.mark.parametrize(
    "path",
    [
        "decisions/secret.md",
        "profile/unflagged.md",
        "projects/missing.md",
        "../outside-secret.env",
        "/etc/passwd",
    ],
)
def test_get_page_hides_private_missing_and_escaping_paths(brain, path: str) -> None:
    assert get_page(brain, path) == {"error": "not found"}


WINS_BODY = (
    "# Wins\n\nDated, one-line entries.\n\n"
    "- 2025-07-08 — Shipped the first thing.\n"
    "- 2026-10-17 — Shipped the newest thing.\n"
    "- 2026-01-02 — Shipped a middle thing.\n"
)


def test_recent_wins_is_empty_until_wins_page_is_public(brain, tmp_path: Path) -> None:
    assert recent_wins(brain) == []
    (tmp_path / "wins.md").write_text(WINS_BODY, encoding="utf-8")
    assert recent_wins(open_brain(tmp_path)) == []


def test_recent_wins_returns_newest_first_and_respects_limit(
    brain, tmp_path: Path
) -> None:
    _write(tmp_path, "wins.md", "true", WINS_BODY.split("\n", 1)[1])
    wins = recent_wins(open_brain(tmp_path))
    assert [win["date"] for win in wins] == ["2026-10-17", "2026-01-02", "2025-07-08"]
    assert wins[0] == {"date": "2026-10-17", "text": "Shipped the newest thing."}
    assert len(recent_wins(open_brain(tmp_path), limit=1)) == 1
    assert len(recent_wins(open_brain(tmp_path), limit=10_000)) == 3
    assert len(recent_wins(open_brain(tmp_path), limit=0)) == 1


def test_get_resume_returns_public_variant(brain, tmp_path: Path) -> None:
    _write(tmp_path, "profile/resume-variants/eng.md", "true", "Resume body.")
    resume = get_resume(open_brain(tmp_path))
    assert resume["path"] == "profile/resume-variants/eng.md"
    assert "Resume body." in resume["body"]


def test_get_resume_hides_unpublished_missing_and_invalid_variants(
    brain, tmp_path: Path
) -> None:
    (tmp_path / "profile/resume-variants").mkdir(parents=True)
    (tmp_path / "profile/resume-variants/ai-eng.md").write_text(
        "<!-- placeholder -->\n", encoding="utf-8"
    )
    b = open_brain(tmp_path)
    assert get_resume(b, "ai-eng") == {"error": "not found"}
    assert get_resume(b, "missing") == {"error": "not found"}
    assert get_resume(b, "../../projects/public") == {"error": "not found"}
    assert get_resume(b, "Eng") == {"error": "not found"}


def test_server_exposes_only_the_four_tools(brain) -> None:
    server = build_server(brain)
    names = sorted(tool.name for tool in asyncio.run(server.list_tools()))
    assert names == ["get_page", "get_resume", "recent_wins", "search_brain"]
