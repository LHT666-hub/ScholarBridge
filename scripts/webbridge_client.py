#!/usr/bin/env python3
"""Small standard-library client for the local Kimi WebBridge daemon."""

from __future__ import annotations

import json
import socket
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


class WebBridgeError(RuntimeError):
    """Raised when the local WebBridge daemon cannot complete a command."""


class WebBridgeClient:
    def __init__(
        self,
        *,
        base_url: str = "http://127.0.0.1:10086",
        session: str = "scholarbridge-authorized",
        timeout: int = 30,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.session = session
        self.timeout = timeout

    def command(self, action: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = json.dumps(
            {
                "action": action,
                "args": args or {},
                "session": self.session,
            },
            ensure_ascii=False,
        ).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/command",
            data=payload,
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Accept": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise WebBridgeError(
                f"WebBridge command {action!r} failed with HTTP {exc.code}: "
                f"{body[:500] or exc.reason}"
            ) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise WebBridgeError(f"WebBridge command {action!r} failed: {exc}") from exc
        try:
            result = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise WebBridgeError(
                f"WebBridge returned invalid JSON for {action!r}: {raw[:200]!r}"
            ) from exc
        if not isinstance(result, dict):
            raise WebBridgeError(f"WebBridge returned a non-object for {action!r}")
        if result.get("success") is False or result.get("error"):
            raise WebBridgeError(
                f"WebBridge command {action!r} failed: "
                f"{result.get('error') or result.get('message') or result}"
            )
        return result

    def navigate(self, url: str, *, new_tab: bool = True, group_title: str = "") -> dict[str, Any]:
        args: dict[str, Any] = {"url": url, "newTab": new_tab}
        if group_title:
            args["group_title"] = group_title
        return self.command("navigate", args)

    def snapshot(self) -> dict[str, Any]:
        return self.command("snapshot")

    def click(self, selector: str) -> dict[str, Any]:
        return self.command("click", {"selector": selector})

    def fill(self, selector: str, value: str) -> dict[str, Any]:
        return self.command("fill", {"selector": selector, "value": value})

    def list_tabs(self) -> dict[str, Any]:
        return self.command("list_tabs")

    def find_tab(self, url: str) -> dict[str, Any]:
        return self.command("find_tab", {"url": url})


def daemon_ready(host: str = "127.0.0.1", port: int = 10086, timeout: float = 0.4) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def start_local_daemon() -> bool:
    executable = (
        Path.home() / ".kimi-webbridge" / "bin" / "kimi-webbridge.exe"
        if __import__("os").name == "nt"
        else Path.home() / ".kimi-webbridge" / "bin" / "kimi-webbridge"
    )
    if not executable.exists():
        return False
    completed = subprocess.run(
        [str(executable), "start"],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return completed.returncode == 0

