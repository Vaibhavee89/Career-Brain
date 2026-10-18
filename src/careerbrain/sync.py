"""Copy only public pages from a brain checkout into a serving directory.

The API filters on `public: true` at query time, but a container that holds
the full data repo still has every private page on disk. This copies the
config plus public pages only, so private content never reaches the host.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from collections.abc import Sequence
from pathlib import Path

from careerbrain.config import CONFIG_FILENAME
from careerbrain.core.retrieval import _SKIP_DIRS, parse_page


def copy_public(src: Path, dst: Path) -> int:
    src = src.resolve()
    if not (src / CONFIG_FILENAME).is_file():
        raise FileNotFoundError(f"{CONFIG_FILENAME} missing under {src}")

    dst.mkdir(parents=True, exist_ok=True)
    copied = 0
    for file in sorted(src.rglob("*.md")):
        rel = file.relative_to(src)
        if any(part in _SKIP_DIRS or part.startswith(".") for part in rel.parts):
            continue
        if not file.is_file() or not file.resolve().is_relative_to(src):
            continue
        page = parse_page(rel.as_posix(), file.read_text(encoding="utf-8"))
        if not page.is_public:
            continue
        target = dst / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(file, target)
        copied += 1

    if copied == 0:
        # Fail closed: an empty brain would silently answer every question with nothing.
        raise RuntimeError(f"no public pages under {src}; refusing to publish")

    shutil.copyfile(src / CONFIG_FILENAME, dst / CONFIG_FILENAME)
    return copied


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Copy public brain pages only.")
    parser.add_argument("--src", type=Path, required=True)
    parser.add_argument("--dst", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        count = copy_public(args.src, args.dst)
    except (FileNotFoundError, RuntimeError) as exc:
        print(exc, file=sys.stderr)
        return 1
    print(f"copied {count} public pages to {args.dst}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
