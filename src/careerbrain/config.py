from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

CONFIG_FILENAME = "brain.config.yaml"


@dataclass(frozen=True)
class BrainConfig:
    root: Path
    paths: dict[str, str] = field(default_factory=dict)
    default_visibility: bool = False


def load_config(root: Path) -> BrainConfig:
    root = root.resolve()
    data = yaml.safe_load((root / CONFIG_FILENAME).read_text(encoding="utf-8")) or {}
    publish = data.get("publish") or {}
    return BrainConfig(
        root=root,
        paths={str(k): str(v) for k, v in (data.get("paths") or {}).items()},
        default_visibility=bool(publish.get("default_visibility", False)),
    )
