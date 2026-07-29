#!/usr/bin/env python3
"""Check ScholarBridge's runtime, configuration, and optional API credentials."""

from __future__ import annotations

import argparse
import json
import os
import platform
import sys
from pathlib import Path

from common import request_bytes


def run(online: bool) -> dict[str, object]:
    checks: dict[str, object] = {
        "python": sys.version.split()[0],
        "python_supported": sys.version_info >= (3, 10),
        "platform": platform.platform(),
        "contact_email_configured": bool(os.environ.get("SCHOLARBRIDGE_EMAIL")),
        "openalex_api_key_configured": bool(os.environ.get("OPENALEX_API_KEY")),
        "core_api_key_configured": bool(os.environ.get("CORE_API_KEY")),
        "online": {},
    }
    if online:
        endpoints = {
            "crossref": "https://api.crossref.org/works?rows=0",
            "pmc": "https://www.ncbi.nlm.nih.gov/pmc/utils/oa/oa.fcgi",
            "doaj": "https://doaj.org/api/search/articles/_exists_:id?pageSize=1",
        }
        results = {}
        for name, url in endpoints.items():
            try:
                data, content_type, final_url = request_bytes(url, max_bytes=1024 * 1024)
                results[name] = {
                    "ok": bool(data),
                    "content_type": content_type,
                    "final_url": final_url,
                }
            except Exception as exc:  # doctor should report all checks, not stop early
                results[name] = {"ok": False, "error": str(exc)}
        checks["online"] = results
    return checks


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--online", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = run(args.online)
    text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    print(text, end="")
    online_ok = all(item.get("ok") for item in result["online"].values()) if args.online else True
    return 0 if result["python_supported"] and online_ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
