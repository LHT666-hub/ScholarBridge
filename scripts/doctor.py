#!/usr/bin/env python3
"""Check ScholarBridge's runtime, configuration, and optional API credentials."""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import socket
import subprocess
import sys
import importlib.util
from pathlib import Path

from common import request_bytes


def _port_open(host: str, port: int, timeout: float = 0.3) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _webbridge_status(home: Path) -> dict[str, object]:
    executable = (
        home / ".kimi-webbridge" / "bin" / "kimi-webbridge.exe"
        if os.name == "nt"
        else home / ".kimi-webbridge" / "bin" / "kimi-webbridge"
    )
    if not executable.exists():
        return {"installed": False}
    try:
        completed = subprocess.run(
            [str(executable), "status"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
        parsed = json.loads(completed.stdout) if completed.stdout.strip() else {}
        return {
            "installed": True,
            "command_ok": completed.returncode == 0,
            **(parsed if isinstance(parsed, dict) else {}),
        }
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        return {"installed": True, "command_ok": False, "error": str(exc)}


def run(online: bool) -> dict[str, object]:
    home = Path.home()
    checks: dict[str, object] = {
        "python": sys.version.split()[0],
        "python_supported": sys.version_info >= (3, 10),
        "platform": platform.platform(),
        "contact_email_configured": bool(os.environ.get("SCHOLARBRIDGE_EMAIL")),
        "openalex_api_key_configured": bool(os.environ.get("OPENALEX_API_KEY")),
        "core_api_key_configured": bool(os.environ.get("CORE_API_KEY")),
        "authorized_browser": {
            "kimi_webbridge_skill_codex": (
                home / ".codex" / "skills" / "kimi-webbridge" / "SKILL.md"
            ).exists(),
            "kimi_webbridge_skill_claude": (
                home / ".claude" / "skills" / "kimi-webbridge" / "SKILL.md"
            ).exists(),
            "kimi_webbridge_daemon_10086": _port_open("127.0.0.1", 10086),
            "kimi_webbridge_status": _webbridge_status(home),
            "cnki_mcp_command": bool(shutil.which("cnki-mcp")),
            "python_playwright_installed": (
                importlib.util.find_spec("playwright") is not None
            ),
            "chrome_executable": next(
                (
                    str(path)
                    for path in (
                        Path(os.environ.get("PROGRAMFILES", "C:/Program Files"))
                        / "Google/Chrome/Application/chrome.exe",
                        Path(os.environ.get("PROGRAMFILES(X86)", "C:/Program Files (x86)"))
                        / "Google/Chrome/Application/chrome.exe",
                        Path(os.environ.get("LOCALAPPDATA", ""))
                        / "Google/Chrome/Application/chrome.exe",
                    )
                    if path.is_file()
                ),
                "",
            ),
        },
        "zotero": {
            "desktop_connector_23119": _port_open("127.0.0.1", 23119),
            "mcp_23120": _port_open("127.0.0.1", 23120),
            "zotero_mcp_command": bool(shutil.which("zotero-mcp")),
            "zotero_cli_command": bool(shutil.which("zotero-cli")),
        },
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
