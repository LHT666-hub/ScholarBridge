#!/usr/bin/env python3
"""Build a deterministic ScholarBridge skill ZIP."""

from __future__ import annotations

import argparse
import zipfile
from pathlib import Path


INCLUDE_DIRS = ("agents", "assets", "references", "scripts")
INCLUDE_ROOT = ("SKILL.md", "SECURITY.md")
EXCLUDE_NAMES = {"__pycache__", ".pytest_cache"}
EXCLUDE_SUFFIXES = {".pyc", ".part"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("dist/skill.zip"))
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    files = [root / name for name in INCLUDE_ROOT if (root / name).exists()]
    for directory in INCLUDE_DIRS:
        base = root / directory
        if not base.exists():
            continue
        files.extend(
            path
            for path in base.rglob("*")
            if path.is_file()
            and not any(part in EXCLUDE_NAMES for part in path.parts)
            and path.suffix not in EXCLUDE_SUFFIXES
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(args.output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(files):
            relative = path.relative_to(root)
            info = zipfile.ZipInfo.from_file(path, arcname=str(Path("scholar-bridge") / relative))
            info.date_time = (2026, 1, 1, 0, 0, 0)
            archive.writestr(info, path.read_bytes())
    print(f"wrote {args.output} ({len(files)} files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
