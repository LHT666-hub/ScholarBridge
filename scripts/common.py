#!/usr/bin/env python3
"""Shared helpers for ScholarBridge's auditable open-PDF workflow."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import re
import socket
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable
from functools import lru_cache


USER_AGENT = "ScholarBridge/0.2 (+https://github.com/LHT666-hub/ScholarBridge)"
DOI_RE = re.compile(r"10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.I)
ARXIV_RE = re.compile(
    r"(?:arxiv:|arxiv\.org/(?:abs|pdf)/)?"
    r"((?:\d{4}\.\d{4,5}|[a-z-]+(?:\.[A-Z]{2})?/\d{7})(?:v\d+)?)",
    re.I,
)
PMCID_RE = re.compile(r"\b(PMC\d+)\b", re.I)


class ScholarBridgeError(RuntimeError):
    """Base error for expected workflow failures."""


class UnsafeUrlError(ScholarBridgeError):
    """Raised when an input URL targets a local or private network."""


@dataclass
class Record:
    record_id: str
    title: str = ""
    doi: str = ""
    url: str = ""
    pdf_url: str = ""
    arxiv_id: str = ""
    pmcid: str = ""
    authors: str = ""
    year: str = ""
    source: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Record":
        fields = {
            key: data.get(key, "")
            for key in (
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
            )
        }
        fields["raw"] = data.get("raw", {})
        if not fields["record_id"]:
            fields["record_id"] = make_record_id(fields)
        return cls(**fields)


@dataclass(frozen=True)
class Candidate:
    provider: str
    url: str
    landing_page: str = ""
    license: str = ""
    version: str = ""
    note: str = ""

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


def normalize_doi(value: Any) -> str:
    text = str(value or "").strip()
    text = re.sub(r"^(?:doi\s*:\s*|https?://(?:dx\.)?doi\.org/)", "", text, flags=re.I)
    match = DOI_RE.search(text)
    if not match:
        return ""
    return match.group(0).rstrip(".,;:)]}").lower()


def normalize_arxiv_id(value: Any) -> str:
    text = str(value or "").strip()
    match = ARXIV_RE.search(text)
    return match.group(1) if match else ""


def normalize_pmcid(value: Any) -> str:
    match = PMCID_RE.search(str(value or ""))
    return match.group(1).upper() if match else ""


def make_record_id(data: dict[str, Any]) -> str:
    identity = (
        normalize_doi(data.get("doi"))
        or normalize_arxiv_id(data.get("arxiv_id"))
        or normalize_pmcid(data.get("pmcid"))
        or str(data.get("pdf_url") or data.get("url") or data.get("title") or "").strip().lower()
    )
    return hashlib.sha1(identity.encode("utf-8")).hexdigest()[:12]


def safe_filename(value: str, fallback: str = "paper", max_length: int = 150) -> str:
    value = re.sub(r"[\x00-\x1f<>:\"/\\|?*]+", "_", value or "")
    value = re.sub(r"\s+", " ", value).strip(" ._")
    if not value:
        value = fallback
    return value[:max_length].rstrip(" ._")


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig") as handle:
        for line_no, line in enumerate(handle, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ScholarBridgeError(f"{path}:{line_no}: invalid JSON: {exc}") from exc
    return rows


def _is_public_ip(value: str) -> bool:
    ip = ipaddress.ip_address(value)
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def validate_public_url(url: str, allow_private: bool = False) -> None:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise UnsafeUrlError(f"unsupported URL: {url}")
    if allow_private:
        return
    try:
        addresses = {
            result[4][0]
            for result in socket.getaddrinfo(parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM)
        }
    except socket.gaierror as exc:
        raise ScholarBridgeError(f"cannot resolve host {parsed.hostname}: {exc}") from exc
    if not addresses or any(not _is_public_ip(address) for address in addresses):
        raise UnsafeUrlError(f"refusing local/private target: {url}")


def build_request(url: str, *, email: str = "", headers: dict[str, str] | None = None) -> urllib.request.Request:
    effective_headers = {
        "User-Agent": f"{USER_AGENT}{f' mailto:{email}' if email else ''}",
        "Accept": "application/json, application/pdf;q=0.9, text/html;q=0.5, */*;q=0.1",
    }
    if headers:
        effective_headers.update(headers)
    return urllib.request.Request(url, headers=effective_headers)


@lru_cache(maxsize=1)
def tls_context() -> ssl.SSLContext:
    """Use Python, optional certifi, and Windows trust roots without disabling TLS."""
    context = ssl.create_default_context()
    try:
        import certifi  # type: ignore

        context.load_verify_locations(cafile=certifi.where())
    except (ImportError, OSError, ssl.SSLError):
        pass
    if sys.platform == "win32" and hasattr(ssl, "enum_certificates"):
        for certificate, encoding, _trust in ssl.enum_certificates("ROOT"):
            if encoding != "x509_asn":
                continue
            try:
                context.load_verify_locations(cadata=ssl.DER_cert_to_PEM_cert(certificate))
            except ssl.SSLError:
                continue
    return context


class SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    def __init__(self, allow_private: bool) -> None:
        super().__init__()
        self.allow_private = allow_private

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> urllib.request.Request | None:
        validate_public_url(newurl, allow_private=self.allow_private)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def open_request(
    request: urllib.request.Request,
    *,
    timeout: int,
    allow_private: bool = False,
) -> Any:
    opener = urllib.request.build_opener(
        urllib.request.HTTPSHandler(context=tls_context()),
        SafeRedirectHandler(allow_private),
    )
    return opener.open(request, timeout=timeout)


def request_bytes(
    url: str,
    *,
    email: str = "",
    headers: dict[str, str] | None = None,
    timeout: int = 30,
    retries: int = 2,
    allow_private: bool = False,
    max_bytes: int = 4 * 1024 * 1024,
) -> tuple[bytes, str, str]:
    validate_public_url(url, allow_private=allow_private)
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            with open_request(
                build_request(url, email=email, headers=headers),
                timeout=timeout,
                allow_private=allow_private,
            ) as response:
                data = response.read(max_bytes + 1)
                if len(data) > max_bytes:
                    raise ScholarBridgeError(f"response exceeded {max_bytes} bytes: {url}")
                return data, response.headers.get_content_type(), response.geturl()
        except urllib.error.HTTPError as exc:
            last_error = exc
            if exc.code not in {429, 500, 502, 503, 504} or attempt >= retries:
                raise ScholarBridgeError(f"HTTP {exc.code}: {url}") from exc
            retry_after = exc.headers.get("Retry-After", "")
            delay = min(float(retry_after), 10.0) if retry_after.isdigit() else (1.0 + attempt)
            time.sleep(delay)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = exc
            if attempt >= retries:
                raise ScholarBridgeError(f"request failed: {url}: {exc}") from exc
            time.sleep(1.0 + attempt)
    raise ScholarBridgeError(f"request failed: {url}: {last_error}")


def request_json(url: str, **kwargs: Any) -> dict[str, Any]:
    data, _, _ = request_bytes(url, **kwargs)
    try:
        payload = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ScholarBridgeError(f"invalid JSON response: {url}") from exc
    if not isinstance(payload, dict):
        raise ScholarBridgeError(f"expected JSON object: {url}")
    return payload


def validate_pdf(path: Path, min_bytes: int = 512) -> dict[str, Any]:
    result: dict[str, Any] = {
        "path": str(path),
        "valid": False,
        "size": 0,
        "sha256": "",
        "has_pdf_header": False,
        "has_eof": False,
        "error": "",
    }
    try:
        size = path.stat().st_size
        result["size"] = size
        if size < min_bytes:
            result["error"] = f"file too small ({size} bytes)"
            return result
        with path.open("rb") as handle:
            header = handle.read(8)
            handle.seek(max(0, size - 2048))
            tail = handle.read()
        result["has_pdf_header"] = header.startswith(b"%PDF-")
        result["has_eof"] = b"%%EOF" in tail
        if not result["has_pdf_header"]:
            result["error"] = "missing %PDF- header"
            return result
        if not result["has_eof"]:
            result["error"] = "missing %%EOF marker"
            return result
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        result["sha256"] = digest.hexdigest()
        result["valid"] = True
        return result
    except OSError as exc:
        result["error"] = str(exc)
        return result
