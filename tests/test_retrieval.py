from pathlib import Path

import pytest

from careerbrain.core.retrieval import (
    PathTraversalError,
    get_public_page,
    search_public,
)


def _page(title: str, public: str | None, body: str) -> str:
    front = f"---\ntype: project\n"
    if public is not None:
        front += f"public: {public}\n"
    return f"{front}---\n\n# {title}\n\n{body}\n"


@pytest.fixture
def brain(tmp_path: Path) -> Path:
    root = tmp_path / "brain"
    (root / "projects").mkdir(parents=True)
    (root / "decisions").mkdir()

    (root / "projects/public-a.md").write_text(
        _page("Public A", "true", "airflow dag failures and airflow retries")
    )
    (root / "projects/public-b.md").write_text(
        _page("Public B", "true", "airflow appears once here")
    )
    (root / "decisions/private-false.md").write_text(
        _page("Private", "false", "airflow secret airflow airflow")
    )
    (root / "decisions/private-missing.md").write_text(
        _page("No flag", None, "airflow secret")
    )
    (root / "decisions/private-capitalized.md").write_text(
        _page("Capitalized", "True", "airflow secret")
    )

    (tmp_path / ".env").write_text("OPENAI_API_KEY=sk-test\n")
    return root


def test_search_never_returns_private_pages(brain: Path) -> None:
    paths = {r.page.path for r in search_public(brain, "airflow secret")}
    assert paths == {"projects/public-a.md", "projects/public-b.md"}


def test_get_public_page_returns_none_for_private_pages(brain: Path) -> None:
    assert get_public_page(brain, "decisions/private-false.md") is None
    assert get_public_page(brain, "decisions/private-missing.md") is None
    assert get_public_page(brain, "decisions/private-capitalized.md") is None


def test_get_public_page_returns_public_page(brain: Path) -> None:
    page = get_public_page(brain, "projects/public-a.md")
    assert page is not None
    assert page.is_public


@pytest.mark.parametrize("rel_path", ["../.env", "projects/../../.env", "/etc/passwd"])
def test_get_public_page_rejects_paths_outside_root(brain: Path, rel_path: str) -> None:
    with pytest.raises(PathTraversalError):
        get_public_page(brain, rel_path)


def test_get_public_page_rejects_symlink_escaping_root(brain: Path, tmp_path: Path) -> None:
    secret = tmp_path / "outside.md"
    secret.write_text(_page("Outside", "true", "leaked"))
    (brain / "projects/link.md").symlink_to(secret)
    with pytest.raises(PathTraversalError):
        get_public_page(brain, "projects/link.md")


def test_search_ranks_by_term_count(brain: Path) -> None:
    results = search_public(brain, "airflow")
    assert [r.page.path for r in results] == [
        "projects/public-a.md",
        "projects/public-b.md",
    ]
    assert results[0].score > results[1].score


def test_search_empty_query_returns_nothing(brain: Path) -> None:
    assert search_public(brain, "   ") == []
