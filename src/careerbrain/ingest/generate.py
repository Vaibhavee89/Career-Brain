from __future__ import annotations

import datetime as dt
import re
from collections.abc import Sequence
from pathlib import Path

from careerbrain.core.types import Page

RESUME_DIR = "profile/resume-variants"
PROFILE_README = "generated/profile-README.md"
GENERATED_NOTE = (
    "<!-- Generated from public pages by careerbrain.ingest. Do not edit by hand. -->"
)
AI_TAGS = frozenset(
    {"ai", "llm", "llm-agents", "llm-integration", "mcp", "evals", "agents"}
)
CITATION = re.compile(r"\s*\(?source:.*$", re.IGNORECASE)
COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)


def generate_outputs(root: Path, pages: Sequence[Page], today: dt.date) -> list[str]:
    public = [page for page in pages if page.is_public]
    written = []
    for variant in ("eng", "ai-eng"):
        path = root / RESUME_DIR / f"{variant}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(build_resume(public, variant, today), encoding="utf-8")
        written.append(path.relative_to(root).as_posix())

    readme = root / PROFILE_README
    readme.parent.mkdir(parents=True, exist_ok=True)
    readme.write_text(build_profile_readme(public), encoding="utf-8")
    written.append(readme.relative_to(root).as_posix())
    return written


def build_resume(pages: Sequence[Page], variant: str, today: dt.date) -> str:
    projects = [p for p in pages if p.frontmatter.get("type") == "project"]
    experience = [p for p in pages if p.frontmatter.get("type") == "experience"]
    if variant == "ai-eng":
        projects = [
            p for p in projects if AI_TAGS & set(_list(p.frontmatter.get("skills")))
        ]
    if not projects and not experience:
        return _frontmatter(variant, today, public=False) + "No public entries yet.\n"

    sections = ["# Resume" + (" (AI / LLM engineering)" if variant == "ai-eng" else "")]
    if experience:
        sections.append("## Experience")
        for page in experience:
            sections.append(_experience_block(page))
    if projects:
        sections.append("## Projects")
        for page in projects:
            sections.append(_project_block(page))
    body = "\n\n".join(sections)
    return _frontmatter(variant, today, public=True) + body + "\n"


def build_profile_readme(pages: Sequence[Page]) -> str:
    about = next((page for page in pages if page.path == "profile/about.md"), None)
    projects = [p for p in pages if p.frontmatter.get("type") == "project"]
    experience = [p for p in pages if p.frontmatter.get("type") == "experience"]

    parts = [GENERATED_NOTE]
    if about is not None:
        pitch = _section(about.body, "3-line pitch")
        if pitch:
            parts.append(pitch)
        roles = _section(about.body, "Target roles")
        if roles:
            parts.append("## Target roles\n" + roles)
    if projects:
        parts.append("## Projects\n" + "\n".join(_project_summary(p) for p in projects))
    if experience:
        parts.append(
            "## Experience\n" + "\n".join(_experience_summary(p) for p in experience)
        )
    if about is not None:
        contact = _section(about.body, "Contact")
        if contact:
            parts.append("## Contact\n" + contact)
    return "\n\n".join(parts) + "\n"


def _frontmatter(variant: str, today: dt.date, *, public: bool) -> str:
    return (
        "---\n"
        "type: resume\n"
        f"variant: {variant}\n"
        f"updated: {today.isoformat()}\n"
        f"public: {'true' if public else 'false'}\n"
        "---\n\n"
        f"{GENERATED_NOTE}\n\n"
    )


def _project_block(page: Page) -> str:
    return f"### {_title(page)}\n" + "\n".join(_bullets(page.body))


def _experience_block(page: Page) -> str:
    fm = page.frontmatter
    heading = f"### {fm.get('company', '')} — {fm.get('role', '')}".rstrip(" —")
    dates = f"{fm.get('start', '')} – {fm.get('end', '')}".strip(" –")
    return f"{heading}\n{dates}\n" + "\n".join(_bullets(page.body))


def _project_summary(page: Page) -> str:
    what = _section(page.body, "What it is").split("\n")[0].strip()
    return f"- **{_title(page)}**" + (f" — {what}" if what else "")


def _experience_summary(page: Page) -> str:
    fm = page.frontmatter
    return f"- **{fm.get('company', '')}** — {fm.get('role', '')} ({fm.get('start', '')}–{fm.get('end', '')})"


def _title(page: Page) -> str:
    for line in page.body.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    stem = page.path.rsplit("/", 1)[-1].removesuffix(".md")
    return stem.replace("-", " ").title()


def _bullets(body: str) -> list[str]:
    bullets = []
    for line in COMMENT.sub("", body).splitlines():
        if line.startswith("- "):
            text = CITATION.sub("", line).rstrip()
            if text.strip("- ").strip():
                bullets.append(text)
    return bullets


def _section(body: str, heading: str) -> str:
    text = COMMENT.sub("", body)
    lines = text.split("\n")
    try:
        start = lines.index(f"## {heading}")
    except ValueError:
        return ""
    collected = []
    for line in lines[start + 1 :]:
        if line.startswith("## "):
            break
        collected.append(line)
    return "\n".join(collected).strip()


def _list(value: str | None) -> list[str]:
    if not value:
        return []
    return [
        item.strip().strip("'\"")
        for item in value.strip("[]").split(",")
        if item.strip()
    ]
