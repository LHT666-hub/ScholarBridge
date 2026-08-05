#!/usr/bin/env python3
"""Import new validated PDFs through Zotero's local Connector server."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from common import read_jsonl, write_jsonl
from execute_zotero_handoff import SEARCH_ALIASES, _search, _tool_name
from mcp_http_client import MCPError, MCPHTTPClient
from zotero_connector_client import ZoteroConnectorClient, ZoteroConnectorError


def run(
    handoff_path: Path,
    output_dir: Path,
    *,
    mcp_url: str,
    connector_url: str,
    execute: bool,
    max_tasks: int,
) -> dict[str, Any]:
    tasks = read_jsonl(handoff_path)
    selected = tasks[:max_tasks] if max_tasks > 0 else tasks
    remainder = tasks[len(selected) :]
    mcp = MCPHTTPClient(mcp_url)
    mcp.initialize()
    tools = mcp.list_tools()
    search_name = _tool_name(tools, SEARCH_ALIASES)
    if not search_name:
        raise MCPError("Zotero MCP has no supported search tool for duplicate checking")
    connector = ZoteroConnectorClient(connector_url)
    if not connector.ping():
        raise ZoteroConnectorError("Zotero Connector is not reachable; keep Zotero Desktop open")
    updated = []
    for task in selected:
        row = dict(task)
        query = str(task.get("doi") or task.get("title") or "")
        existing_key, _ = _search(mcp, tools, search_name, query)
        if existing_key:
            row.update(
                {
                    "state": "zotero-existing-needs-attachment",
                    "zotero_item_key": existing_key,
                    "zotero_error": (
                        "The installed MCP is read-only and the Connector new-item "
                        "flow would create a duplicate; attach this PDF manually or "
                        "install a write-capable Zotero MCP."
                    ),
                }
            )
        elif not execute:
            row.update({"state": "zotero-connector-dry-run", "zotero_error": ""})
        else:
            try:
                result = connector.create_item_with_pdf(task)
                verified_key, _ = _search(mcp, tools, search_name, query)
                row.update(
                    {
                        "state": (
                            "zotero-complete" if verified_key else "zotero-write-unverified"
                        ),
                        "zotero_item_key": verified_key,
                        "zotero_operation": "connector-created-item-and-uploaded-pdf",
                        "zotero_result": result,
                        "zotero_error": "",
                    }
                )
            except (ZoteroConnectorError, MCPError) as exc:
                row.update({"state": "zotero-failed", "zotero_error": str(exc)})
        updated.append(row)
    updated.extend(remainder)
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / "zotero-connector.executed.jsonl"
    write_jsonl(output, updated)
    states: dict[str, int] = {}
    for row in updated:
        state = str(row.get("state") or "unknown")
        states[state] = states.get(state, 0) + 1
    summary = {
        "tasks": len(updated),
        "execute": execute,
        "states": states,
        "mcp_search_tool": search_name,
        "connector_reachable": True,
        "output": str(output),
    }
    (output_dir / "zotero-connector-summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("handoff", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--mcp-url", default="http://127.0.0.1:23120/mcp")
    parser.add_argument(
        "--connector-url", default="http://127.0.0.1:23119/connector"
    )
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--max-tasks", type=int, default=20)
    args = parser.parse_args()
    summary = run(
        args.handoff,
        args.output_dir,
        mcp_url=args.mcp_url,
        connector_url=args.connector_url,
        execute=args.execute,
        max_tasks=args.max_tasks,
    )
    print(json.dumps(summary, ensure_ascii=False))
    return 2 if summary["states"].get("zotero-failed") else 0


if __name__ == "__main__":
    raise SystemExit(main())
