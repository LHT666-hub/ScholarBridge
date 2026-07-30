#!/usr/bin/env python3
"""Resolve and download legally available scholarly PDFs with an audit trail."""

from __future__ import annotations

import argparse
import csv
import html
import json
import os
import re
import shutil
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from common import (
    Candidate,
    Record,
    ScholarBridgeError,
    build_request,
    safe_filename,
    open_request,
    validate_pdf,
    validate_public_url,
    write_jsonl,
)
from normalize_records import normalize_file
from providers import PROVIDERS, discover, resolve_doi_with_crossref


DEFAULT_PROVIDERS = [
    "direct",
    "arxiv",
    "pmc",
    "europe-pmc",
    "unpaywall",
    "openalex",
    "core",
    "doaj",
]
PDF_META_PATTERNS = [
    re.compile(
        r'<meta[^>]+name=["\']citation_pdf_url["\'][^>]+content=["\']([^"\']+)',
        re.I,
    ),
    re.compile(
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']citation_pdf_url["\']',
        re.I,
    ),
    re.compile(r'href=["\']([^"\']+\.pdf(?:\?[^"\']*)?)["\']', re.I),
]


def _load_records(path: Path) -> list[Record]:
    if path.suffix.lower() == ".jsonl":
        records = []
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            if line.strip():
                records.append(Record.from_dict(json.loads(line)))
        return records
    accepted, _, _ = normalize_file(path)
    return accepted


def _extract_pdf_links(data: bytes, base_url: str) -> list[str]:
    text = data.decode("utf-8", errors="ignore")
    links: list[str] = []
    seen: set[str] = set()
    for pattern in PDF_META_PATTERNS:
        for match in pattern.finditer(text):
            url = urllib.parse.urljoin(base_url, html.unescape(match.group(1)))
            if url not in seen:
                seen.add(url)
                links.append(url)
    return links[:10]


def _stream_response(
    response: Any,
    destination: Path,
    *,
    max_bytes: int,
    first_chunk: bytes,
) -> int:
    total = len(first_chunk)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("wb") as handle:
        handle.write(first_chunk)
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                raise ScholarBridgeError(f"PDF exceeded {max_bytes} bytes")
            handle.write(chunk)
    return total


def download_candidate(
    candidate: Candidate,
    destination: Path,
    *,
    email: str,
    timeout: int,
    max_bytes: int,
    allow_private: bool,
    html_depth: int = 1,
) -> tuple[dict[str, Any], Path | None]:
    validate_public_url(candidate.url, allow_private=allow_private)
    temp_path = destination.with_suffix(destination.suffix + ".part")
    temp_path.unlink(missing_ok=True)
    try:
        request = build_request(candidate.url, email=email)
        with open_request(
            request,
            timeout=timeout,
            allow_private=allow_private,
        ) as response:
            final_url = response.geturl()
            validate_public_url(final_url, allow_private=allow_private)
            content_type = response.headers.get_content_type()
            first = response.read(8192)
            if first.startswith(b"%PDF-") or content_type == "application/pdf":
                _stream_response(
                    response,
                    temp_path,
                    max_bytes=max_bytes,
                    first_chunk=first,
                )
                verification = validate_pdf(temp_path)
                if not verification["valid"]:
                    raise ScholarBridgeError(str(verification["error"]))
                temp_path.replace(destination)
                verification["path"] = str(destination)
                verification.update(
                    {
                        "provider": candidate.provider,
                        "resolved_url": final_url,
                        "content_type": content_type,
                    }
                )
                return verification, destination

            if html_depth > 0 and content_type in {"text/html", "application/xhtml+xml"}:
                html_data = first + response.read(max(0, 2 * 1024 * 1024 - len(first)))
                links = _extract_pdf_links(html_data, final_url)
                errors = []
                for link in links:
                    nested = Candidate(
                        provider=candidate.provider,
                        url=link,
                        landing_page=candidate.landing_page or final_url,
                        license=candidate.license,
                        version=candidate.version,
                        note="resolved from HTML metadata",
                    )
                    try:
                        return download_candidate(
                            nested,
                            destination,
                            email=email,
                            timeout=timeout,
                            max_bytes=max_bytes,
                            allow_private=allow_private,
                            html_depth=html_depth - 1,
                        )
                    except ScholarBridgeError as exc:
                        errors.append(str(exc))
                reason = "HTML page did not expose a valid PDF"
                if errors:
                    reason += ": " + " | ".join(errors[:3])
                raise ScholarBridgeError(reason)
            raise ScholarBridgeError(
                f"not a PDF (content-type={content_type}, final_url={final_url})"
            )
    except urllib.error.HTTPError as exc:
        raise ScholarBridgeError(f"HTTP {exc.code}: {candidate.url}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ScholarBridgeError(f"download failed: {candidate.url}: {exc}") from exc
    finally:
        temp_path.unlink(missing_ok=True)


def _destination_for(record: Record, output_dir: Path) -> Path:
    author = ""
    if record.authors:
        author = re.split(r"[;,]|\band\b", record.authors, maxsplit=1, flags=re.I)[0].strip()
    label = "_".join(
        part
        for part in (
            record.year,
            author,
            record.title or record.doi or record.arxiv_id or record.pmcid or record.record_id,
        )
        if part
    )
    preferred = output_dir / f"{safe_filename(label, record.record_id)}.pdf"
    if not preferred.exists():
        return preferred
    index = 2
    while True:
        candidate = preferred.with_name(f"{preferred.stem}_{index}{preferred.suffix}")
        if not candidate.exists():
            return candidate
        index += 1


def _deduplicate_destination(path: Path, sha256: str, known_hashes: dict[str, Path]) -> tuple[Path, bool]:
    if sha256 in known_hashes:
        return known_hashes[sha256], True
    known_hashes[sha256] = path
    return path, False


def _write_manifest(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = [
        "record_id",
        "title",
        "doi",
        "arxiv_id",
        "pmcid",
        "status",
        "provider",
        "license",
        "version",
        "pdf_path",
        "sha256",
        "resolved_url",
        "attempt_count",
        "reason",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _load_resumable_manifest(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    completed: dict[str, dict[str, Any]] = {}
    for row in rows:
        if row.get("status") not in {"downloaded", "duplicate"}:
            continue
        pdf_path = Path(str(row.get("pdf_path") or ""))
        if not pdf_path.is_file():
            continue
        check = validate_pdf(pdf_path)
        if not check["valid"]:
            continue
        row["sha256"] = check["sha256"]
        row["pdf_path"] = str(pdf_path)
        completed[str(row.get("record_id") or "")] = row
    return completed


def _write_report(path: Path, rows: list[dict[str, Any]], provider_names: list[str]) -> None:
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    lines = [
        "# ScholarBridge acquisition report",
        "",
        f"- Records: {len(rows)}",
        f"- Providers: {', '.join(provider_names)}",
    ]
    for status in sorted(counts):
        lines.append(f"- {status}: {counts[status]}")
    lines.extend(
        [
            "",
            "Only files that passed `%PDF-`, size, `%%EOF`, and SHA-256 checks are marked downloaded.",
            "",
            "## Unresolved records",
            "",
            "| Record | DOI/title | Status | Reason |",
            "|---|---|---|---|",
        ]
    )
    unresolved = [row for row in rows if row["status"] not in {"downloaded", "duplicate"}]
    for row in unresolved:
        identity = row.get("doi") or row.get("title") or row["record_id"]
        reason = str(row.get("reason") or "").replace("|", "\\|")
        lines.append(f"| {row['record_id']} | {identity} | {row['status']} | {reason} |")
    if not unresolved:
        lines.append("| — | — | — | All records resolved |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(
    input_path: Path,
    output_dir: Path,
    *,
    execute: bool,
    email: str,
    provider_names: list[str],
    openalex_api_key: str,
    core_api_key: str,
    max_records: int,
    max_mb: int,
    timeout: int,
    delay: float,
    allow_private: bool,
    resume: bool = False,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    pdf_dir = output_dir / "pdf"
    pdf_dir.mkdir(exist_ok=True)
    records = _load_records(input_path)
    if max_records > 0:
        records = records[:max_records]
    manifest: list[dict[str, Any]] = []
    attempt_log: list[dict[str, Any]] = []
    plan_rows: list[dict[str, Any]] = []
    resumable = (
        _load_resumable_manifest(output_dir / "manifest.csv")
        if resume and execute
        else {}
    )
    resumed = 0
    known_hashes: dict[str, Path] = {}
    for existing in pdf_dir.glob("*.pdf"):
        check = validate_pdf(existing)
        if check["valid"]:
            known_hashes[check["sha256"]] = existing

    for record in records:
        previous = resumable.get(record.record_id)
        if previous:
            previous = dict(previous)
            previous["attempt_count"] = 0
            previous["reason"] = "resumed from validated existing manifest"
            manifest.append(previous)
            plan_rows.append(
                {
                    "record": record.to_dict(),
                    "identifier_resolution": {"status": "resumed"},
                    "candidates": [],
                    "discovery_errors": [],
                }
            )
            resumed += 1
            continue
        resolution: dict[str, Any] = {}
        if (
            not record.doi
            and record.title
            and not (record.pdf_url or record.arxiv_id or record.pmcid)
        ):
            try:
                record, resolution = resolve_doi_with_crossref(
                    record,
                    email=email,
                    timeout=timeout,
                )
            except ScholarBridgeError as exc:
                resolution = {
                    "provider": "crossref",
                    "status": "error",
                    "error": str(exc),
                }
        candidates, discovery_errors = discover(
            record,
            provider_names,
            email=email,
            openalex_api_key=openalex_api_key,
            core_api_key=core_api_key,
            timeout=timeout,
        )
        plan_rows.append(
            {
                "record": record.to_dict(),
                "identifier_resolution": resolution,
                "candidates": [candidate.to_dict() for candidate in candidates],
                "discovery_errors": discovery_errors,
            }
        )
        base = {
            "record_id": record.record_id,
            "title": record.title,
            "doi": record.doi,
            "arxiv_id": record.arxiv_id,
            "pmcid": record.pmcid,
            "provider": "",
            "license": "",
            "version": "",
            "pdf_path": "",
            "sha256": "",
            "resolved_url": "",
            "attempt_count": 0,
            "reason": "",
        }
        if not execute:
            manifest.append(
                {
                    **base,
                    "status": "dry_run",
                    "reason": f"{len(candidates)} candidate(s); no download attempted",
                }
            )
            continue
        if not candidates:
            errors = "; ".join(f"{item['provider']}: {item['error']}" for item in discovery_errors)
            manifest.append(
                {
                    **base,
                    "status": "no_open_pdf",
                    "reason": errors or "no open PDF candidate found",
                }
            )
            continue

        destination = _destination_for(record, pdf_dir)
        failures = []
        completed = False
        for attempt_number, candidate in enumerate(candidates, 1):
            attempt = {
                "record_id": record.record_id,
                "provider": candidate.provider,
                "url": candidate.url,
                "status": "failed",
                "error": "",
            }
            try:
                verification, downloaded_path = download_candidate(
                    candidate,
                    destination,
                    email=email,
                    timeout=timeout,
                    max_bytes=max_mb * 1024 * 1024,
                    allow_private=allow_private,
                )
                assert downloaded_path is not None
                final_path, duplicate = _deduplicate_destination(
                    downloaded_path,
                    verification["sha256"],
                    known_hashes,
                )
                if duplicate:
                    downloaded_path.unlink(missing_ok=True)
                elif final_path != downloaded_path:
                    shutil.move(str(downloaded_path), str(final_path))
                attempt["status"] = "downloaded"
                attempt_log.append(attempt)
                manifest.append(
                    {
                        **base,
                        "status": "duplicate" if duplicate else "downloaded",
                        "provider": candidate.provider,
                        "license": candidate.license,
                        "version": candidate.version,
                        "pdf_path": str(final_path),
                        "sha256": verification["sha256"],
                        "resolved_url": verification["resolved_url"],
                        "attempt_count": attempt_number,
                    }
                )
                completed = True
                break
            except ScholarBridgeError as exc:
                attempt["error"] = str(exc)
                attempt_log.append(attempt)
                failures.append(f"{candidate.provider}: {exc}")
            if delay:
                time.sleep(delay)
        if not completed:
            manifest.append(
                {
                    **base,
                    "status": "failed",
                    "attempt_count": len(candidates),
                    "reason": " | ".join(failures[:8]),
                }
            )
        if delay:
            time.sleep(delay)

    write_jsonl(output_dir / "plan.jsonl", plan_rows)
    write_jsonl(output_dir / "attempts.jsonl", attempt_log)
    _write_manifest(output_dir / "manifest.csv", manifest)
    _write_report(output_dir / "report.md", manifest, provider_names)
    summary = {
        "records": len(records),
        "downloaded": sum(row["status"] == "downloaded" for row in manifest),
        "duplicates": sum(row["status"] == "duplicate" for row in manifest),
        "unresolved": sum(row["status"] not in {"downloaded", "duplicate"} for row in manifest),
        "resumed": resumed,
        "execute": execute,
        "output_dir": str(output_dir),
    }
    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="CSV/TSV/JSON/JSONL/RIS/BibTeX/TXT input")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--execute", action="store_true", help="Download; otherwise only build a plan")
    parser.add_argument("--email", default=os.environ.get("SCHOLARBRIDGE_EMAIL", ""))
    parser.add_argument(
        "--providers",
        default=",".join(DEFAULT_PROVIDERS),
        help="Comma-separated provider names",
    )
    parser.add_argument(
        "--openalex-api-key",
        default=os.environ.get("OPENALEX_API_KEY", ""),
    )
    parser.add_argument("--core-api-key", default=os.environ.get("CORE_API_KEY", ""))
    parser.add_argument("--max-records", type=int, default=100)
    parser.add_argument("--max-mb", type=int, default=100)
    parser.add_argument("--timeout", type=int, default=45)
    parser.add_argument("--delay", type=float, default=1.0)
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Reuse validated downloaded/duplicate rows from an existing manifest.",
    )
    parser.add_argument(
        "--allow-private",
        action="store_true",
        help="Allow localhost/private URLs (intended only for controlled tests)",
    )
    args = parser.parse_args()
    provider_names = [item.strip() for item in args.providers.split(",") if item.strip()]
    unknown = sorted(set(provider_names) - set(PROVIDERS))
    if unknown:
        parser.error(f"unknown providers: {', '.join(unknown)}")
    if args.email and "@" not in args.email:
        parser.error("--email must be a valid contact email")
    summary = run(
        args.input,
        args.output_dir,
        execute=args.execute,
        email=args.email,
        provider_names=provider_names,
        openalex_api_key=args.openalex_api_key,
        core_api_key=args.core_api_key,
        max_records=args.max_records,
        max_mb=args.max_mb,
        timeout=args.timeout,
        delay=args.delay,
        allow_private=args.allow_private,
        resume=args.resume,
    )
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if (not args.execute or summary["unresolved"] == 0) else 2


if __name__ == "__main__":
    raise SystemExit(main())
