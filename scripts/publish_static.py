#!/usr/bin/env python3
"""Copy live map assets into docs/ (GitHub Pages) and build/ (bothost)."""

from __future__ import annotations

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGETS = [ROOT / "docs", ROOT / "build"]

FILES = [
    "index.html",
    "sync-api.json",
    "sync-mirror.json",
    "server.py",  # bothost image may use build/; harmless on Pages if ignored
]

DIRS = [
    "data",
    "js",
]


def copy_tree(src: Path, dst: Path) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)


def main() -> None:
    for target in TARGETS:
        target.mkdir(parents=True, exist_ok=True)
        for name in FILES:
            src = ROOT / name
            if not src.exists():
                continue
            # Keep server.py out of docs/ (Pages is static).
            if target.name == "docs" and name == "server.py":
                continue
            shutil.copy2(src, target / name)
            print(f"copied {name} -> {target.name}/")
        for name in DIRS:
            src = ROOT / name
            if not src.exists():
                continue
            copy_tree(src, target / name)
            print(f"copied {name}/ -> {target.name}/{name}/")
        # Preserve docs/m redirect and secrets doc.
        print(f"done {target}")


if __name__ == "__main__":
    main()
