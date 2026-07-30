#!/usr/bin/env python3
"""Build an offline route plan before making any scholarly network request."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from common import Record, write_jsonl
from normalize_records import normalize_file
from prepare_authorized_queue import detect_platform


def load(path: Path) -> list[Record]:
    if path.suffix.lower() == ".jsonl":
        return [
            Record.from_dict(json.loads(line))
            for line in path.read_text(encoding="utf-8-sig").splitlines()
            if line.strip()
        ]
    return normalize_file(path)[0]


def routes(record: Record) -> list[str]:
    result = []
    if record.pdf_url:
        result.append("direct")
    if record.arxiv_id:
        result.append("arxiv")
    if record.pmcid:
        result.append("pmc")
    if record.doi:
        result.extend(["europe-pmc", "unpaywall", "openalex", "core", "doaj"])
    if record.url and not record.pdf_url:
        platform = detect_platform(record)
        if platform == "google-scholar":
            result.append("google-scholar-discovery")
        else:
            result.append(f"authorized-browser:{platform}")
    if not result:
        result.append("identifier-resolution-required")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    rows = [{"record": record.to_dict(), "routes": routes(record)} for record in load(args.input)]
    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_jsonl(args.output_dir / "plan.jsonl", rows)
    print(json.dumps({"records": len(rows), "output": str(args.output_dir / "plan.jsonl")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
