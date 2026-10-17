from __future__ import annotations

from dataclasses import dataclass


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
