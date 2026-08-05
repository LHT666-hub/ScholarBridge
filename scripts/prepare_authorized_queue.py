#!/usr/bin/env python3
"""Prepare a browser handoff queue for institution-authorized PDF downloads."""

from __future__ import annotations

import argparse
import json
import urllib.parse
from pathlib import Path
from typing import Any

from common import Record, safe_filename, write_jsonl
from normalize_records import normalize_file
from platform_adapters import get_platform_adapter


PLATFORM_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("cnki", ("cnki.net", "cnki", "知网")),
    ("wanfang", ("wanfangdata.com.cn", "wanfang", "万方")),
    ("cqvip", ("cqvip.com", "cqvip", "维普")),
    ("web-of-science", ("webofscience.com", "web of science")),
    ("scopus", ("scopus.com", "scopus")),
    ("proquest", ("proquest.com", "proquest")),
    ("ebsco", ("ebscohost.com", "ebsco")),
    ("science-direct", ("sciencedirect.com", "elsevier")),
    ("springer-nature", ("springer.com", "nature.com", "springer nature")),
    ("wiley", ("onlinelibrary.wiley.com", "wiley")),
    ("ieee", ("ieeexplore.ieee.org", "ieee")),
)

HOME_URLS = {
    "cnki": "https://www.cnki.net/",
    "wanfang": "https://www.wanfangdata.com.cn/",
    "cqvip": "https://www.cqvip.com/",
    "web-of-science": "https://www.webofscience.com/",
    "scopus": "https://www.scopus.com/",
    "proquest": "https://www.proquest.com/",
    "ebsco": "https://search.ebscohost.com/",
}


def load_records(path: Path) -> list[Record]:
    if path.suffix.lower() == ".jsonl":
        rows: list[Record] = []
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            if line.strip():
                rows.append(Record.from_dict(json.loads(line)))
        return rows
    return normalize_file(path)[0]


def detect_platform(record: Record) -> str:
    haystack = " ".join((record.url, record.pdf_url, record.source)).lower()
    for platform, markers in PLATFORM_RULES:
        if any(marker in haystack for marker in markers):
            return platform
    if "scholar.google." in haystack or "谷歌学术" in haystack:
        return "google-scholar"
    if record.url:
        return "publisher-or-library"
    if record.doi:
        return "doi-resolver"
    return "discovery-required"


def start_url(record: Record, platform: str) -> str:
    if record.url:
        return record.url
    if record.doi:
        return f"https://doi.org/{urllib.parse.quote(record.doi, safe='/')}"
    adapter = get_platform_adapter(platform)
    return adapter.home_url if adapter else HOME_URLS.get(platform, "")


def queue_row(record: Record) -> dict[str, Any]:
    platform = detect_platform(record)
    adapter = get_platform_adapter(platform)
    if platform == "google-scholar":
        state = "discovery-only"
    elif adapter and adapter.role == "licensed-index":
        state = "discovery-export-only"
    elif platform == "discovery-required":
        state = "identifier-or-url-required"
    else:
        state = "awaiting-user-authentication"
    target = safe_filename(record.title, fallback=record.record_id) + ".pdf"
    return {
        "queue_id": f"auth-{record.record_id}",
        "record_id": record.record_id,
        "title": record.title,
        "doi": record.doi,
        "authors": record.authors,
        "year": record.year,
        "source": record.source,
        "platform": platform,
        "route": (
            "licensed-discovery"
            if adapter and adapter.role == "licensed-index"
            else "authorized-visible-browser"
        ),
        "access_class": (
            "licensed-index"
            if adapter and adapter.role == "licensed-index"
            else "authorized-subscription"
        ),
        "state": state,
        "start_url": start_url(record, platform),
        "target_filename": target,
        "downloaded_filename": "",
        "expected_format": "pdf",
        "preferred_backend": adapter.preferred_backend if adapter else "webbridge",
        "notes": adapter.notes if adapter else "",
    }


def write_handoff(path: Path, rows: list[dict[str, Any]]) -> None:
    actionable = sum(row["state"] == "awaiting-user-authentication" for row in rows)
    discovery = sum(row["state"] != "awaiting-user-authentication" for row in rows)
    body = f"""# Authorized browser handoff

- Queue records: {len(rows)}
- Ready for an authenticated browser: {actionable}
- Need discovery or identifier repair: {discovery}

## Execution contract

1. Open a visible local browser profile. Prefer an already-running browser connection
   (Kimi WebBridge or Playwright MCP extension) so the user's existing login remains in
   the browser. A dedicated persistent Playwright profile is an alternative.
2. Let the user complete institution, VPN, CARSI, WebVPN, Shibboleth, OpenAthens,
   account login, and any CAPTCHA. Never ask the user to paste credentials into chat.
3. Use the platform's visible, native PDF download control. Do not discover hidden
   endpoints, copy cookies into this project, or bypass a download limit.
4. Stop the platform route on CAPTCHA, 403, 429, account/IP warning, or an explicit
   automation prohibition. Record the stop reason in the queue.
5. After each native download, write its actual filename into `downloaded_filename`.
6. Run `scripts/ingest_downloads.py` to validate and archive the PDFs.

Google Scholar is discovery-only: export citations or follow an authorized provider
link, then route the resulting DOI/URL through ScholarBridge.
"""
    path.write_text(body, encoding="utf-8")


def run(input_path: Path, output_dir: Path) -> dict[str, Any]:
    rows = [queue_row(record) for record in load_records(input_path)]
    output_dir.mkdir(parents=True, exist_ok=True)
    write_jsonl(output_dir / "authorized-queue.jsonl", rows)
    write_handoff(output_dir / "browser-handoff.md", rows)
    summary = {
        "records": len(rows),
        "actionable": sum(row["state"] == "awaiting-user-authentication" for row in rows),
        "output": str(output_dir / "authorized-queue.jsonl"),
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
    print(json.dumps(run(args.input, args.output_dir), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
