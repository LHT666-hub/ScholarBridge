#!/usr/bin/env python3
"""Validate browser-downloaded PDFs and reconcile them with an authorized queue."""

from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from common import read_jsonl, safe_filename, validate_pdf, write_jsonl


PARTIAL_SUFFIXES = {".crdownload", ".part", ".download", ".tmp"}


def _norm(value: str) -> str:
    return re.sub(r"[^\w\u3400-\u9fff]+", "", value or "").casefold()


def _score(row: dict[str, Any], path: Path) -> int:
    filename = path.name.casefold()
    if row.get("downloaded_filename") and filename == str(row["downloaded_filename"]).casefold():
        return 100
    if filename == str(row.get("target_filename", "")).casefold():
        return 98
    if row.get("record_id") and str(row["record_id"]).casefold() in filename:
        return 95
    title = _norm(str(row.get("title", "")))
    stem = _norm(path.stem)
    if not title or not stem:
        return 0
    if title == stem:
        return 92
    if min(len(title), len(stem)) >= 8 and (title in stem or stem in title):
        return 82
    ratio = SequenceMatcher(None, title, stem).ratio()
    return 70 if ratio >= 0.72 else 0


def _unique_destination(root: Path, name: str, record_id: str) -> Path:
    candidate = root / name
    if not candidate.exists():
        return candidate
    return root / f"{Path(name).stem} [{record_id}].pdf"


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = [
        "record_id",
        "title",
        "doi",
        "platform",
        "status",
        "source_file",
        "pdf_path",
        "size",
        "sha256",
        "match_score",
        "error",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def run(queue_path: Path, download_dir: Path, output_dir: Path) -> dict[str, Any]:
    queue = read_jsonl(queue_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    pdf_dir = output_dir / "pdf"
    pdf_dir.mkdir(parents=True, exist_ok=True)

    partials = sorted(
        path for path in download_dir.rglob("*") if path.is_file() and path.suffix.lower() in PARTIAL_SUFFIXES
    )
    candidates = sorted(
        path for path in download_dir.rglob("*") if path.is_file() and path.suffix.lower() == ".pdf"
    )
    validation = {path: validate_pdf(path) for path in candidates}
    valid_files = [path for path in candidates if validation[path]["valid"]]
    used: set[Path] = set()
    known_hashes: dict[str, Path] = {}
    manifest: list[dict[str, Any]] = []
    updated_queue: list[dict[str, Any]] = []

    for row in queue:
        ranked = sorted(
            ((_score(row, path), path) for path in valid_files if path not in used),
            key=lambda pair: (-pair[0], pair[1].name.casefold()),
        )
        best_score = ranked[0][0] if ranked else 0
        tied = [path for score, path in ranked if score == best_score and score > 0]
        if not tied and len(valid_files) - len(used) == 1 and len(queue) == 1:
            tied = [next(path for path in valid_files if path not in used)]
            best_score = 60

        result = {
            "record_id": row.get("record_id", ""),
            "title": row.get("title", ""),
            "doi": row.get("doi", ""),
            "platform": row.get("platform", ""),
            "status": "unmatched",
            "source_file": "",
            "pdf_path": "",
            "size": 0,
            "sha256": "",
            "match_score": best_score,
            "error": "",
        }
        new_row = dict(row)
        if len(tied) != 1:
            if len(tied) > 1:
                result["error"] = "ambiguous filename match"
            else:
                result["error"] = "no validated PDF matched this queue item"
            updated_queue.append(new_row)
            manifest.append(result)
            continue

        source = tied[0]
        used.add(source)
        check = validation[source]
        digest = str(check["sha256"])
        target_name = safe_filename(
            str(row.get("title") or source.stem),
            fallback=str(row.get("record_id") or "paper"),
        ) + ".pdf"
        if digest in known_hashes:
            destination = known_hashes[digest]
            status = "duplicate"
        else:
            destination = _unique_destination(pdf_dir, target_name, str(row.get("record_id", "")))
            shutil.copy2(source, destination)
            known_hashes[digest] = destination
            status = "ingested"
        result.update(
            {
                "status": status,
                "source_file": str(source),
                "pdf_path": str(destination.resolve()),
                "size": check["size"],
                "sha256": digest,
                "error": "",
            }
        )
        new_row["state"] = "pdf-ingested"
        new_row["downloaded_filename"] = source.name
        new_row["pdf_path"] = str(destination.resolve())
        new_row["sha256"] = digest
        updated_queue.append(new_row)
        manifest.append(result)

    for path in candidates:
        if validation[path]["valid"] or path in used:
            continue
        manifest.append(
            {
                "record_id": "",
                "title": "",
                "doi": "",
                "platform": "",
                "status": "invalid-pdf",
                "source_file": str(path),
                "pdf_path": "",
                "size": validation[path]["size"],
                "sha256": "",
                "match_score": 0,
                "error": validation[path]["error"],
            }
        )

    _write_csv(output_dir / "ingest-manifest.csv", manifest)
    write_jsonl(output_dir / "authorized-queue.updated.jsonl", updated_queue)
    summary = {
        "queue_records": len(queue),
        "pdf_candidates": len(candidates),
        "ingested": sum(row["status"] == "ingested" for row in manifest),
        "duplicates": sum(row["status"] == "duplicate" for row in manifest),
        "unmatched": sum(row["status"] == "unmatched" for row in manifest),
        "invalid": sum(row["status"] == "invalid-pdf" for row in manifest),
        "partial_downloads": [str(path) for path in partials],
    }
    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("queue", type=Path)
    parser.add_argument("--download-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    summary = run(args.queue, args.download_dir, args.output_dir)
    print(json.dumps(summary, ensure_ascii=False))
    return 2 if summary["partial_downloads"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
