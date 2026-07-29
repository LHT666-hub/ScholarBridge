#!/usr/bin/env python3
"""Verify PDF signatures, EOF markers, hashes, and exact duplicates."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from common import validate_pdf


def run(pdf_dir: Path, output_dir: Path) -> dict[str, int]:
    output_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    seen: dict[str, str] = {}
    for path in sorted(pdf_dir.rglob("*.pdf")):
        result = validate_pdf(path)
        result["duplicate_of"] = ""
        if result["valid"] and result["sha256"] in seen:
            result["duplicate_of"] = seen[result["sha256"]]
        elif result["valid"]:
            seen[result["sha256"]] = str(path)
        rows.append(result)
    fields = [
        "path",
        "valid",
        "size",
        "sha256",
        "has_pdf_header",
        "has_eof",
        "duplicate_of",
        "error",
    ]
    with (output_dir / "pdf-verification.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    summary = {
        "files": len(rows),
        "valid": sum(bool(row["valid"]) for row in rows),
        "invalid": sum(not bool(row["valid"]) for row in rows),
        "duplicates": sum(bool(row["duplicate_of"]) for row in rows),
    }
    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf_dir", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    summary = run(args.pdf_dir, args.output_dir)
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if summary["invalid"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
