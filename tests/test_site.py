from pathlib import Path

import pytest

from careerbrain.site.build import build_site


def _write(root: Path, rel: str, text: str) -> None:
    target = root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


@pytest.fixture
def brain(tmp_path: Path) -> Path:
    _write(tmp_path, "brain.config.yaml", "paths: {}\n")
    _write(
        tmp_path,
        "profile/about.md",
        "---\ntype: profile\npublic: true\n---\n\n## 3-line pitch\nI build AI systems.\n\n"
        "## Who I am\n<!-- TODO: private note -->\nVisible intro.\n\n"
        "## Contact\n- Email: me@example.com\n",
    )
    _write(
        tmp_path,
        "projects/etl.md",
        "---\ntype: project\npublic: true\nskills: [python, mcp]\n---\n\n# ETL Helper\n\n"
        "## What it is\nAn agent for DAG failures.\n\n- Built with **MCP**.\n",
    )
    _write(
        tmp_path,
        "projects/secret.md",
        "---\ntype: project\npublic: false\n---\n\n# Secret Project\n\n- Confidential metric 4242.\n",
    )
    _write(tmp_path, "wins.md", "# Wins\n\n- 2026-01-01 — Shipped something.\n")
    return tmp_path


def _all_text(out: Path) -> str:
    return "\n".join(path.read_text(encoding="utf-8") for path in out.rglob("*.html"))


def test_builds_index_chat_and_public_pages_only(brain: Path, tmp_path: Path) -> None:
    out = tmp_path / "site"
    build_site(brain, out, api_url="https://api.example.com")

    assert (out / "index.html").is_file()
    assert (out / "ask-me.html").is_file()
    assert (out / "pages/projects--etl.html").is_file()
    assert (out / "pages/profile--about.html").is_file()
    assert not (out / "pages/projects--secret.html").exists()
    assert not (out / "pages/wins.html").exists()


def test_private_content_never_appears_in_output(brain: Path, tmp_path: Path) -> None:
    out = tmp_path / "site"
    build_site(brain, out, api_url=None)
    text = _all_text(out)
    assert "Secret Project" not in text
    assert "Confidential" not in text
    assert "4242" not in text
    assert "Shipped something" not in text


def test_html_comments_and_titles_are_handled(brain: Path, tmp_path: Path) -> None:
    out = tmp_path / "site"
    build_site(brain, out)
    text = _all_text(out)
    assert "private note" not in text
    assert "TODO" not in text
    assert text.count("<h1>ETL Helper</h1>") == 1
    assert "<strong>MCP</strong>" in text


def test_index_has_pitch_and_links_to_public_pages(brain: Path, tmp_path: Path) -> None:
    out = tmp_path / "site"
    build_site(brain, out)
    index = (out / "index.html").read_text(encoding="utf-8")
    assert "I build AI systems." in index
    assert 'href="pages/projects--etl.html"' in index
    assert "secret" not in index.lower()


def test_chat_config_is_embedded_safely(brain: Path, tmp_path: Path) -> None:
    out = tmp_path / "site"
    build_site(brain, out, api_url="https://x.example</script><script>alert(1)")
    chat = (out / "ask-me.html").read_text(encoding="utf-8")
    assert "</script><script>alert(1)" not in chat
    assert "window.CAREERBRAIN" in chat


def test_chat_disabled_without_api_url(brain: Path, tmp_path: Path) -> None:
    out = tmp_path / "site"
    build_site(brain, out, api_url=None)
    chat = (out / "ask-me.html").read_text(encoding="utf-8")
    assert '"apiUrl": null' in chat
    assert "Chat is not configured" in chat


def test_chat_renders_answers_as_text_not_html(brain: Path, tmp_path: Path) -> None:
    out = tmp_path / "site"
    build_site(brain, out, api_url="https://api.example.com")
    chat = (out / "ask-me.html").read_text(encoding="utf-8")
    assert "textContent" in chat
    assert "innerHTML" not in chat


def test_no_external_resources_are_loaded(brain: Path, tmp_path: Path) -> None:
    out = tmp_path / "site"
    build_site(brain, out, api_url="https://api.example.com")
    text = _all_text(out)
    assert 'src="http' not in text
    assert 'href="http' not in text.replace("https://api.example.com", "")
