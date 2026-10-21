from __future__ import annotations

import re
from pathlib import Path

from careerbrain.core.types import Page, PathTraversalError, SearchResult

_SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__"}
_TOKEN_RE = re.compile(r"[a-z0-9]+")
LOG_TYPE = "log"
LOG_SCORE_DIVISOR = 4


def parse_page(path: str, text: str) -> Page:
    frontmatter: dict[str, str] = {}
    body = text
    if text.startswith("---\n"):
        end = text.find("\n---", 4)
        if end != -1:
            for line in text[4:end].splitlines():
                key, sep, value = line.partition(":")
                if not sep or not key.strip() or key.startswith(" "):
                    continue
                value = value.split(" #", 1)[0].strip().strip("\"'")
                frontmatter[key.strip()] = value
            body = text[end + len("\n---") :].lstrip("\n")
    return Page(path=path, frontmatter=frontmatter, body=body)


def resolve_inside(root: Path, rel_path: str) -> Path:
    root = root.resolve()
    candidate = (root / rel_path).resolve()
    if not candidate.is_relative_to(root):
        raise PathTraversalError(f"path escapes brain root: {rel_path}")
    return candidate


def load_pages(root: Path) -> list[Page]:
    root = root.resolve()
    pages: list[Page] = []
    for file in sorted(root.rglob("*.md")):
        rel = file.relative_to(root)
        if any(part in _SKIP_DIRS or part.startswith(".") for part in rel.parts):
            continue
        if not file.is_file() or not file.resolve().is_relative_to(root):
            continue
        pages.append(parse_page(rel.as_posix(), file.read_text(encoding="utf-8")))
    return pages


def get_public_page(root: Path, rel_path: str) -> Page | None:
    target = resolve_inside(root, rel_path)
    if not target.is_file():
        return None
    page = parse_page(rel_path, target.read_text(encoding="utf-8"))
    return page if page.is_public else None


def search_public(root: Path, query: str, limit: int = 5) -> list[SearchResult]:
    terms = set(_TOKEN_RE.findall(query.lower()))
    if not terms:
        return []

    results: list[SearchResult] = []
    for page in load_pages(root):
        if not page.is_public:
            continue
        score, snippet = _score(page, terms)
        if score:
            results.append(SearchResult(page=page, score=score, snippet=snippet))

    results.sort(key=lambda r: (-r.score, r.page.path))
    return results[:limit]


def _score(page: Page, terms: set[str]) -> tuple[int, str]:
    score = 0
    snippet = ""
    for line in page.body.splitlines():
        tokens = _TOKEN_RE.findall(line.lower())
        hits = sum(1 for t in tokens if t in terms)
        if hits:
            score += hits
            if not snippet:
                snippet = line.strip()
    title_tokens = _TOKEN_RE.findall(page.path.lower())
    score += 2 * sum(1 for t in title_tokens if t in terms)
    heading = next(
        (line for line in page.body.splitlines() if line.startswith("# ")), ""
    )
    score += 4 * sum(1 for t in _TOKEN_RE.findall(heading.lower()) if t in terms)
    if page.frontmatter.get("type") == LOG_TYPE:
        # Append-only logs match on many lines; down-weight them so curated pages rank.
        score //= LOG_SCORE_DIVISOR
    return score, snippet
