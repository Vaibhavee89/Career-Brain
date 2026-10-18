from pathlib import Path

import pytest

from careerbrain.sync import copy_public, main


def _page(title: str, public: str | None) -> str:
    front = "---\ntype: project\n"
    if public is not None:
        front += f"public: {public}\n"
    return f"{front}---\n\n# {title}\n"


@pytest.fixture
def src(tmp_path: Path) -> Path:
    root = tmp_path / "data"
    (root / "projects").mkdir(parents=True)
    (root / "job-search").mkdir()
    (root / ".git").mkdir()
    (root / "brain.config.yaml").write_text("paths: {}\n")
    (root / "projects/public.md").write_text(_page("Public", "true"))
    (root / "projects/private.md").write_text(_page("Private", "false"))
    (root / "projects/unmarked.md").write_text(_page("Unmarked", None))
    (root / "job-search/notes.md").write_text(_page("Notes", "true"))
    (root / ".git/hidden.md").write_text(_page("Hidden", "true"))
    return root


def test_copies_only_public_pages_and_config(src: Path, tmp_path: Path) -> None:
    dst = tmp_path / "serve"

    count = copy_public(src, dst)

    assert count == 2
    assert (dst / "projects/public.md").is_file()
    assert (dst / "job-search/notes.md").is_file()
    assert (dst / "brain.config.yaml").is_file()
    assert not (dst / "projects/private.md").exists()
    assert not (dst / "projects/unmarked.md").exists()
    assert not (dst / ".git").exists()


def test_refuses_when_no_public_pages(tmp_path: Path) -> None:
    src = tmp_path / "data"
    src.mkdir()
    (src / "brain.config.yaml").write_text("paths: {}\n")
    (src / "secret.md").write_text(_page("Secret", "false"))

    with pytest.raises(RuntimeError, match="no public pages"):
        copy_public(src, tmp_path / "serve")


def test_refuses_without_config(tmp_path: Path) -> None:
    src = tmp_path / "data"
    src.mkdir()
    (src / "page.md").write_text(_page("Page", "true"))

    with pytest.raises(FileNotFoundError, match="brain.config.yaml"):
        copy_public(src, tmp_path / "serve")


def test_main_returns_nonzero_on_failure(tmp_path: Path) -> None:
    src = tmp_path / "data"
    src.mkdir()

    code = main(["--src", str(src), "--dst", str(tmp_path / "serve")])

    assert code == 1
