from __future__ import annotations

import re
from dataclasses import dataclass

PAGES_URL_DIR = "pages"
_URL_RE = re.compile(r"https?://[^\s,\]]+")


class PathTraversalError(ValueError):
    pass


@dataclass(frozen=True)
class Page:
    path: str
    frontmatter: dict[str, str]
    body: str

    @property
    def is_public(self) -> bool:
        return self.frontmatter.get("public") == "true"


@dataclass(frozen=True)
class SearchResult:
    page: Page
    score: int
    snippet: str


def page_slug(path: str) -> str:
    """The file stem build_site publishes a page's path under, e.g.
    "projects/etl.md" -> "projects--etl"."""
    return path.removesuffix(".md").replace("/", "--")


def page_url(base_url: str, path: str) -> str:
    """The public site URL for a page, given the site's base URL."""
    return f"{base_url.rstrip('/')}/{PAGES_URL_DIR}/{page_slug(path)}.html"


def page_links(frontmatter: dict[str, str]) -> list[str]:
    """URLs listed in a page's `links` frontmatter, e.g. repo or demo links."""
    return _URL_RE.findall(frontmatter.get("links", ""))


def page_title(page: Page) -> str:
    """A page's display title: its first `# ` heading, or a title-cased
    fallback built from its file name."""
    for line in page.body.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return page.path.rsplit("/", 1)[-1].removesuffix(".md").replace("-", " ").title()
