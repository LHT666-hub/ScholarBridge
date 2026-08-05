#!/usr/bin/env python3
"""Minimal Zotero Connector client for creating an item and uploading its PDF."""

from __future__ import annotations

import json
import secrets
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


class ZoteroConnectorError(RuntimeError):
    """Raised when the local Zotero Connector server rejects an operation."""


class ZoteroConnectorClient:
    def __init__(self, base_url: str = "http://127.0.0.1:23119/connector", *, timeout: int = 60) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _request(
        self,
        endpoint: str,
        *,
        data: bytes | None = None,
        headers: dict[str, str] | None = None,
        method: str = "POST",
    ) -> tuple[int, bytes]:
        request = urllib.request.Request(
            f"{self.base_url}/{endpoint.lstrip('/')}",
            data=data,
            headers=headers or {},
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise ZoteroConnectorError(
                f"Zotero Connector HTTP {exc.code}: {body[:500]}"
            ) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise ZoteroConnectorError(f"Zotero Connector request failed: {exc}") from exc

    def ping(self) -> bool:
        try:
            status, _ = self._request("ping", method="GET")
        except ZoteroConnectorError:
            return False
        return 200 <= status < 300

    @staticmethod
    def _creators(authors: str) -> list[dict[str, str]]:
        creators = []
        for raw in authors.replace(" and ", ";").split(";"):
            name = raw.strip()
            if not name:
                continue
            if "," in name:
                last, first = (part.strip() for part in name.split(",", 1))
            else:
                parts = name.split()
                first, last = (" ".join(parts[:-1]), parts[-1]) if len(parts) > 1 else ("", name)
            creators.append(
                {
                    "creatorType": "author",
                    "firstName": first,
                    "lastName": last,
                }
            )
        return creators

    def create_item_with_pdf(self, task: dict[str, Any]) -> dict[str, Any]:
        pdf_path = Path(str(task.get("pdf_path") or "")).expanduser().resolve()
        if not pdf_path.is_file():
            raise ZoteroConnectorError(f"PDF does not exist: {pdf_path}")
        session_id = secrets.token_hex(16)
        connector_item_id = secrets.token_hex(16)
        doi = str(task.get("doi") or "")
        source_url = str(task.get("source_url") or "")
        if not source_url and doi:
            source_url = f"https://doi.org/{doi}"
        item = {
            "id": connector_item_id,
            "itemType": "journalArticle",
            "title": str(task.get("title") or pdf_path.stem),
            "creators": self._creators(str(task.get("authors") or "")),
            "date": str(task.get("year") or ""),
            "DOI": doi,
            "url": source_url,
            "tags": [{"tag": "ScholarBridge"}],
            "attachments": [],
        }
        payload = json.dumps(
            {
                "sessionID": session_id,
                "uri": source_url or "https://localhost.invalid/scholarbridge",
                "items": [item],
            },
            ensure_ascii=False,
        ).encode("utf-8")
        status, _ = self._request(
            "saveItems",
            data=payload,
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "X-Zotero-Connector-API-Version": "3",
            },
        )
        if status not in {200, 201}:
            raise ZoteroConnectorError(f"saveItems returned unexpected HTTP {status}")
        pdf = pdf_path.read_bytes()
        metadata = json.dumps(
            {
                "sessionID": session_id,
                "parentItemID": connector_item_id,
                "title": pdf_path.name,
                "url": source_url,
            },
            ensure_ascii=True,
            separators=(",", ":"),
        )
        attachment_status, _ = self._request(
            "saveAttachment",
            data=pdf,
            headers={
                "Content-Type": "application/pdf",
                "Content-Length": str(len(pdf)),
                "X-Metadata": metadata,
                "X-Zotero-Connector-API-Version": "3",
            },
        )
        if attachment_status not in {200, 201}:
            raise ZoteroConnectorError(
                f"saveAttachment returned unexpected HTTP {attachment_status}"
            )
        return {
            "session_id": session_id,
            "connector_item_id": connector_item_id,
            "save_items_status": status,
            "save_attachment_status": attachment_status,
        }
