from __future__ import annotations

import os
from pathlib import Path

from careerbrain.config import CONFIG_FILENAME, BrainConfig, load_config
from careerbrain.core.retrieval import get_public_page, load_pages, search_public
from careerbrain.core.types import Page, SearchResult

ROOT_ENV_VAR = "CAREERBRAIN_ROOT"


class Brain:
    def __init__(self, config: BrainConfig) -> None:
        self.config = config

    def search(self, query: str, limit: int = 5) -> list[SearchResult]:
        return search_public(self.config.root, query, limit=limit)

    def get_page(self, rel_path: str) -> Page | None:
        return get_public_page(self.config.root, rel_path)

    def list_public_pages(self) -> list[Page]:
        return [page for page in load_pages(self.config.root) if page.is_public]


def find_root(start: Path | None = None) -> Path:
    env_root = os.environ.get(ROOT_ENV_VAR)
    if env_root:
        return Path(env_root).resolve()
    current = (start or Path.cwd()).resolve()
    for candidate in (current, *current.parents):
        if (candidate / CONFIG_FILENAME).is_file():
            return candidate
    raise FileNotFoundError(
        f"no {CONFIG_FILENAME} found above {current}; set {ROOT_ENV_VAR}"
    )


def open_brain(root: Path | None = None) -> Brain:
    return Brain(load_config(root or find_root()))
