#!/usr/bin/env python3
"""Normalize DOI/title/URL records from common scholarly export formats."""

from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path
from typing import Any, Iterable

from common import (
    DOI_RE,
    Record,
    make_record_id,
    normalize_arxiv_id,
    normalize_doi,
    normalize_pmcid,
    write_jsonl,
)


ALIASES = {
    "title": ("title", "ti", "t1", "article title", "document title"),
    "doi": ("doi", "di", "digital object identifier"),
    "url": ("url", "ur", "link", "landing_page"),
    "pdf_url": ("pdf_url", "pdf", "full_text_url", "fulltext_url"),
    "arxiv_id": ("arxiv_id", "arxiv", "eprint"),
    "pmcid": ("pmcid", "pmc"),
    "authors": ("authors", "author", "au"),
    "year": ("year", "py", "publication year", "publication_year"),
    "source": ("source", "database", "journal", "jo", "t2"),
}


def _lookup(row: dict[str, Any], field: str) -> Any:
    lowered = {str(key).strip().lower(): value for key, value in row.items()}
    for alias in ALIASES[field]:
        value = lowered.get(alias)
        if value not in (None, ""):
            return value
    return ""


def normalize_mapping(row: dict[str, Any]) -> Record | None:
    title = str(_lookup(row, "title") or "").strip()
    doi = normalize_doi(_lookup(row, "doi"))
    url = str(_lookup(row, "url") or "").strip()
    pdf_url = str(_lookup(row, "pdf_url") or "").strip()
    arxiv_id = normalize_arxiv_id(_lookup(row, "arxiv_id"))
    pmcid = normalize_pmcid(_lookup(row, "pmcid"))
    authors_value = _lookup(row, "authors")
    if isinstance(authors_value, list):
        authors = "; ".join(map(str, authors_value))
    else:
        authors = str(authors_value or "").strip()
    year_match = re.search(r"\b(?:19|20)\d{2}\b", str(_lookup(row, "year") or ""))
    year = year_match.group(0) if year_match else ""
    source = str(_lookup(row, "source") or "").strip()

    combined = " ".join(str(value or "") for value in row.values())
    if not doi:
        doi = normalize_doi(combined)
    if not arxiv_id:
        arxiv_id = normalize_arxiv_id(url) or normalize_arxiv_id(combined)
    if not pmcid:
        pmcid = normalize_pmcid(url) or normalize_pmcid(combined)
    if not pdf_url and url.lower().split("?", 1)[0].endswith(".pdf"):
        pdf_url, url = url, ""

    data = {
        "title": title,
        "doi": doi,
        "url": url,
        "pdf_url": pdf_url,
        "arxiv_id": arxiv_id,
        "pmcid": pmcid,
        "authors": authors,
        "year": year,
        "source": source,
    }
    if not any((title, doi, url, pdf_url, arxiv_id, pmcid)):
        return None
    return Record(record_id=make_record_id(data), raw=row, **data)


def _parse_delimited(path: Path, delimiter: str) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle, delimiter=delimiter))


def _parse_json(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if isinstance(data, dict):
        for key in ("records", "items", "results"):
            if isinstance(data.get(key), list):
                data = data[key]
                break
        else:
            data = [data]
    if not isinstance(data, list):
        raise ValueError("JSON input must be an object or array")
    return [row for row in data if isinstance(row, dict)]


def _parse_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"line {line_no} is not a JSON object")
        rows.append(value)
    return rows


def _parse_ris(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    current: dict[str, Any] = {}
    authors: list[str] = []
    for line in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        match = re.match(r"^([A-Z0-9]{2})  - (.*)$", line)
        if not match:
            continue
        tag, value = match.groups()
        if tag == "TY":
            current, authors = {}, []
        elif tag == "ER":
            if authors:
                current["authors"] = authors
            if current:
                rows.append(current)
            current, authors = {}, []
        elif tag == "AU":
            authors.append(value)
        else:
            current[tag] = value
    if current:
        if authors:
            current["authors"] = authors
        rows.append(current)
    return rows


def _parse_endnote(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    current: dict[str, Any] = {}
    authors: list[str] = []
    mapping = {
        "%T": "title",
        "%D": "year",
        "%R": "doi",
        "%U": "url",
        "%J": "source",
        "%B": "source",
    }
    for line in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        if len(line) < 3 or not line.startswith("%"):
            continue
        tag, value = line[:2], line[3:].strip()
        if tag == "%0":
            if current:
                if authors:
                    current["authors"] = authors
                rows.append(current)
            current, authors = {}, []
        elif tag == "%A":
            authors.append(value)
        elif tag in mapping:
            current[mapping[tag]] = value
    if current:
        if authors:
            current["authors"] = authors
        rows.append(current)
    return rows


def _parse_bibtex(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    starts = list(re.finditer(r"@\w+\s*\{\s*[^,]+,", text, re.I))
    rows: list[dict[str, Any]] = []
    for index, start in enumerate(starts):
        end = starts[index + 1].start() if index + 1 < len(starts) else len(text)
        block = text[start.end() : end]
        row: dict[str, Any] = {}
        for match in re.finditer(
            r"(?ms)^\s*([A-Za-z][\w-]*)\s*=\s*(?:\{(.*?)\}|\"(.*?)\")\s*,?",
            block,
        ):
            row[match.group(1)] = (match.group(2) or match.group(3) or "").strip()
        if row:
            rows.append(row)
    return rows


def _parse_text(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        doi = normalize_doi(line)
        if doi:
            rows.append({"doi": doi, "raw_text": line})
        elif line.startswith(("http://", "https://")):
            rows.append({"url": line})
        else:
            rows.append({"title": line})
    return rows


def load_raw_rows(path: Path) -> list[dict[str, Any]]:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return _parse_delimited(path, ",")
    if suffix == ".tsv":
        return _parse_delimited(path, "\t")
    if suffix == ".json":
        return _parse_json(path)
    if suffix == ".jsonl":
        return _parse_jsonl(path)
    if suffix == ".ris":
        return _parse_ris(path)
    if suffix == ".enw":
        return _parse_endnote(path)
    if suffix in {".bib", ".bibtex"}:
        return _parse_bibtex(path)
    if suffix in {".txt", ".doi", ""}:
        return _parse_text(path)
    raise ValueError(f"unsupported input format: {suffix}")


def normalize_file(path: Path) -> tuple[list[Record], list[Record], list[dict[str, Any]]]:
    accepted: list[Record] = []
    duplicates: list[Record] = []
    rejected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, row in enumerate(load_raw_rows(path), 1):
        record = normalize_mapping(row)
        if record is None:
            rejected.append({"row": index, "reason": "no usable identifier, URL, or title", "raw": row})
            continue
        if record.record_id in seen:
            duplicates.append(record)
            continue
        seen.add(record.record_id)
        accepted.append(record)
    return accepted, duplicates, rejected


def _write_csv(path: Path, rows: Iterable[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def run(input_path: Path, output_dir: Path) -> dict[str, Any]:
    accepted, duplicates, rejected = normalize_file(input_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    write_jsonl(output_dir / "records.jsonl", (record.to_dict() for record in accepted))
    fields = [
        "record_id",
        "title",
        "doi",
        "url",
        "pdf_url",
        "arxiv_id",
        "pmcid",
        "authors",
        "year",
        "source",
    ]
    _write_csv(output_dir / "records.csv", (record.to_dict() for record in accepted), fields)
    _write_csv(output_dir / "duplicates.csv", (record.to_dict() for record in duplicates), fields)
    _write_csv(output_dir / "rejected.csv", rejected, ["row", "reason", "raw"])
    summary = {
        "input": str(input_path),
        "accepted": len(accepted),
        "duplicates": len(duplicates),
        "rejected": len(rejected),
    }
    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    summary = run(args.input, args.output_dir)
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
