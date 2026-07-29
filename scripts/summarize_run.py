#!/usr/bin/env python3
"""Regenerate a Markdown report from a ScholarBridge manifest."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=Path("manifest.csv"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    with args.manifest.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    counts: dict[str, int] = {}
    for row in rows:
        counts[row.get("status", "unknown")] = counts.get(row.get("status", "unknown"), 0) + 1
    lines = ["# ScholarBridge run summary", "", f"- Total: {len(rows)}"]
    lines.extend(f"- {key}: {counts[key]}" for key in sorted(counts))
    lines.extend(["", "## Failures", "", "| ID | DOI/title | Reason |", "|---|---|---|"])
    failures = [row for row in rows if row.get("status") not in {"downloaded", "duplicate"}]
    for row in failures:
        identity = row.get("doi") or row.get("title") or row.get("record_id")
        reason = (row.get("reason") or "").replace("|", "\\|")
        lines.append(f"| {row.get('record_id')} | {identity} | {reason} |")
    if not failures:
        lines.append("| — | — | No failures |")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
