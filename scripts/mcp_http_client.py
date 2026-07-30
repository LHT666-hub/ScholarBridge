#!/usr/bin/env python3
"""Minimal Streamable HTTP MCP client implemented with the Python standard library."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any


class MCPError(RuntimeError):
    """Raised when an MCP transport or JSON-RPC call fails."""


def _decode_sse(data: bytes) -> dict[str, Any]:
    events = []
    for raw_line in data.decode("utf-8", errors="replace").splitlines():
        if raw_line.startswith("data:"):
            value = raw_line[5:].strip()
            if value:
                events.append(value)
    for value in reversed(events):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    raise MCPError("MCP returned an event stream without a JSON-RPC data event")


class MCPHTTPClient:
    def __init__(self, url: str, *, timeout: int = 30) -> None:
        self.url = url
        self.timeout = timeout
        self.session_id = ""
        self.protocol_version = "2025-03-26"
        self.request_id = 0

    def _post(
        self,
        payload: dict[str, Any],
        *,
        expect_response: bool = True,
    ) -> dict[str, Any]:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {
            "Content-Type": "application/json; charset=utf-8",
            "Accept": "application/json, text/event-stream",
        }
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
            headers["MCP-Protocol-Version"] = self.protocol_version
        request = urllib.request.Request(
            self.url,
            data=data,
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read()
                content_type = response.headers.get("Content-Type", "")
                session_id = response.headers.get("Mcp-Session-Id", "")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise MCPError(f"MCP HTTP {exc.code}: {body[:500]}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise MCPError(f"MCP request failed: {exc}") from exc
        if session_id:
            self.session_id = session_id
        if not expect_response or not raw:
            return {}
        try:
            message = (
                _decode_sse(raw)
                if "text/event-stream" in content_type
                else json.loads(raw.decode("utf-8"))
            )
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise MCPError(f"MCP returned invalid JSON: {raw[:300]!r}") from exc
        if not isinstance(message, dict):
            raise MCPError("MCP returned a non-object JSON-RPC message")
        if message.get("error"):
            raise MCPError(f"MCP JSON-RPC error: {message['error']}")
        return message

    def request(self, method: str, params: dict[str, Any] | None = None) -> Any:
        self.request_id += 1
        payload: dict[str, Any] = {
            "jsonrpc": "2.0",
            "id": self.request_id,
            "method": method,
        }
        if params is not None:
            payload["params"] = params
        return self._post(payload).get("result")

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        payload: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            payload["params"] = params
        self._post(payload, expect_response=False)

    def initialize(self) -> dict[str, Any]:
        result = self.request(
            "initialize",
            {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {
                    "name": "scholarbridge",
                    "version": "0.2.0",
                },
            },
        )
        if not isinstance(result, dict):
            raise MCPError("MCP initialize did not return an object")
        if result.get("protocolVersion"):
            self.protocol_version = str(result["protocolVersion"])
        self.notify("notifications/initialized")
        return result

    def list_tools(self) -> list[dict[str, Any]]:
        result = self.request("tools/list", {})
        if not isinstance(result, dict) or not isinstance(result.get("tools"), list):
            raise MCPError("MCP tools/list did not return a tools array")
        return [tool for tool in result["tools"] if isinstance(tool, dict)]

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        result = self.request(
            "tools/call",
            {
                "name": name,
                "arguments": arguments,
            },
        )
        if not isinstance(result, dict):
            raise MCPError(f"MCP tool {name!r} returned a non-object result")
        if result.get("isError"):
            raise MCPError(f"MCP tool {name!r} failed: {result}")
        return result
