#!/usr/bin/env python3
"""Execute and verify ScholarBridge Zotero handoff tasks through an HTTP MCP server."""

from __future__ import annotations

import argparse
import contextlib
import http.server
import json
import secrets
import threading
from pathlib import Path
from typing import Any

from common import read_jsonl, write_jsonl
from mcp_http_client import MCPError, MCPHTTPClient


SEARCH_ALIASES = (
    "search_library",
    "zotero_search",
    "search_items",
    "search",
)
ATTACH_ALIASES = (
    "zotero_attach_file",
    "attach_file",
    "add_attachment",
)
ADD_ALIASES = (
    "zotero_add_from_file",
    "add_from_file",
    "import_pdf",
    "import_file",
)
CREATE_ITEM_ALIASES = ("create_item", "zotero_create_item")
IMPORT_URL_ALIASES = ("import_attachment_url", "zotero_import_attachment_url")


def _tool_name(tools: list[dict[str, Any]], aliases: tuple[str, ...]) -> str:
    names = [str(tool.get("name") or "") for tool in tools]
    lowered = {name.casefold(): name for name in names}
    for alias in aliases:
        if alias.casefold() in lowered:
            return lowered[alias.casefold()]
    for alias in aliases:
        for name in names:
            if alias.casefold() in name.casefold():
                return name
    return ""


def _tool(tools: list[dict[str, Any]], name: str) -> dict[str, Any]:
    return next((tool for tool in tools if tool.get("name") == name), {})


def _properties(tool: dict[str, Any]) -> dict[str, Any]:
    schema = tool.get("inputSchema") or tool.get("input_schema") or {}
    props = schema.get("properties", {}) if isinstance(schema, dict) else {}
    return props if isinstance(props, dict) else {}


def _assign(
    args: dict[str, Any],
    props: dict[str, Any],
    aliases: tuple[str, ...],
    value: Any,
) -> bool:
    lowered = {name.casefold(): name for name in props}
    for alias in aliases:
        if alias.casefold() in lowered:
            args[lowered[alias.casefold()]] = value
            return True
    return False


def _search_args(tool: dict[str, Any], query: str) -> dict[str, Any]:
    props = _properties(tool)
    args: dict[str, Any] = {}
    if not _assign(
        args,
        props,
        ("query", "q", "search", "search_term", "search_query", "term"),
        query,
    ):
        raise MCPError(
            f"cannot map a search query into tool {tool.get('name')!r}; "
            f"properties={sorted(props)}"
        )
    _assign(args, props, ("limit", "max_results", "maxResults"), 10)
    return args


def _file_args(
    tool: dict[str, Any],
    file_path: str,
    *,
    item_key: str = "",
    collection: str = "",
) -> dict[str, Any]:
    props = _properties(tool)
    args: dict[str, Any] = {}
    if not _assign(
        args,
        props,
        ("file_path", "filepath", "path", "pdf_path", "attachment_path"),
        file_path,
    ):
        raise MCPError(
            f"cannot map a file path into tool {tool.get('name')!r}; "
            f"properties={sorted(props)}"
        )
    if item_key and not _assign(
        args,
        props,
        ("item_key", "itemKey", "parent_item_key", "parentKey", "key"),
        item_key,
    ):
        raise MCPError(
            f"cannot map an item key into tool {tool.get('name')!r}; "
            f"properties={sorted(props)}"
        )
    if collection:
        _assign(
            args,
            props,
            ("collection", "collection_name", "collectionName", "collection_key"),
            collection,
        )
    return args


def _create_item_args(tool: dict[str, Any], task: dict[str, Any]) -> dict[str, Any]:
    props = _properties(tool)
    args: dict[str, Any] = {}
    _assign(args, props, ("itemType", "item_type", "type"), "journalArticle")
    fields = {
        "title": str(task.get("title") or ""),
        "DOI": str(task.get("doi") or ""),
        "date": str(task.get("year") or ""),
        "publicationTitle": str(task.get("source") or ""),
    }
    fields = {key: value for key, value in fields.items() if value}
    _assign(args, props, ("fields", "metadata"), fields)
    authors = str(task.get("authors") or "")
    creators = []
    for author in [item.strip() for item in authors.replace("；", ";").split(";") if item.strip()]:
        creators.append({"name": author, "creatorType": "author"})
    if creators:
        _assign(args, props, ("creators", "authors"), creators)
    return args


class _OneFileHandler(http.server.BaseHTTPRequestHandler):
    file_path: Path
    token: str

    def do_GET(self) -> None:  # noqa: N802
        if self.path != f"/{self.token}.pdf":
            self.send_error(404)
            return
        data = self.file_path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "application/pdf")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format: str, *args: object) -> None:
        return


@contextlib.contextmanager
def _serve_local_pdf(path: Path):
    handler = type(
        "ScholarBridgeOneFileHandler",
        (_OneFileHandler,),
        {"file_path": path, "token": secrets.token_urlsafe(18)},
    )
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/{handler.token}.pdf"
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()


def _import_url_args(
    tool: dict[str, Any],
    url: str,
    task: dict[str, Any],
    *,
    item_key: str,
) -> dict[str, Any]:
    props = _properties(tool)
    args: dict[str, Any] = {}
    if not _assign(args, props, ("url", "attachment_url"), url):
        raise MCPError(
            f"cannot map a URL into tool {tool.get('name')!r}; properties={sorted(props)}"
        )
    if item_key:
        _assign(
            args,
            props,
            ("parentItemKey", "parent_item_key", "itemKey", "item_key"),
            item_key,
        )
    _assign(args, props, ("title", "attachment_title"), str(task.get("title") or "PDF"))
    _assign(args, props, ("contentType", "content_type", "mime_type"), "application/pdf")
    _assign(args, props, ("ifExists", "if_exists"), "skip")
    return args


def _json_from_content(result: dict[str, Any]) -> list[Any]:
    values: list[Any] = []
    structured = result.get("structuredContent") or result.get("structured_content")
    if structured is not None:
        values.append(structured)
    content = result.get("content", [])
    if isinstance(content, list):
        for item in content:
            if not isinstance(item, dict):
                continue
            text = item.get("text")
            if not isinstance(text, str):
                continue
            try:
                values.append(json.loads(text))
            except json.JSONDecodeError:
                values.append(text)
    return values


def _item_keys(value: Any) -> list[str]:
    keys: list[str] = []
    if isinstance(value, dict):
        for name, nested in value.items():
            if name.casefold() in {"item_key", "itemkey", "key"} and isinstance(nested, str):
                keys.append(nested)
            else:
                keys.extend(_item_keys(nested))
    elif isinstance(value, list):
        for nested in value:
            keys.extend(_item_keys(nested))
    return keys


def _search(
    client: MCPHTTPClient,
    tools: list[dict[str, Any]],
    search_name: str,
    query: str,
) -> tuple[str, dict[str, Any]]:
    if not query:
        return "", {}
    tool = _tool(tools, search_name)
    result = client.call_tool(search_name, _search_args(tool, query))
    keys = []
    for value in _json_from_content(result):
        keys.extend(_item_keys(value))
    return (keys[0] if keys else ""), result


def execute_task(
    task: dict[str, Any],
    *,
    client: MCPHTTPClient,
    tools: list[dict[str, Any]],
    search_name: str,
    attach_name: str,
    add_name: str,
    create_name: str,
    import_url_name: str,
) -> dict[str, Any]:
    updated = dict(task)
    pdf_path = Path(str(task.get("pdf_path") or "")).resolve()
    if not pdf_path.is_file():
        updated["state"] = "zotero-failed"
        updated["zotero_error"] = f"PDF does not exist: {pdf_path}"
        return updated
    try:
        item_key = ""
        if task.get("doi"):
            item_key, _ = _search(
                client,
                tools,
                search_name,
                str(task["doi"]),
            )
        if not item_key and task.get("title"):
            item_key, _ = _search(
                client,
                tools,
                search_name,
                str(task["title"]),
            )
        if item_key:
            if attach_name:
                result = client.call_tool(
                    attach_name,
                    _file_args(
                        _tool(tools, attach_name),
                        str(pdf_path),
                        item_key=item_key,
                        collection=str(task.get("collection") or ""),
                    ),
                )
            elif import_url_name:
                with _serve_local_pdf(pdf_path) as url:
                    result = client.call_tool(
                        import_url_name,
                        _import_url_args(
                            _tool(tools, import_url_name),
                            url,
                            task,
                            item_key=item_key,
                        ),
                    )
            else:
                raise MCPError(
                    "an existing item was found but no local-file or URL-attachment "
                    "tool is available"
                )
            operation = "attached-to-existing"
        else:
            if add_name:
                result = client.call_tool(
                    add_name,
                    _file_args(
                        _tool(tools, add_name),
                        str(pdf_path),
                        collection=str(task.get("collection") or ""),
                    ),
                )
                operation = "created-from-file"
            elif create_name and import_url_name:
                created = client.call_tool(
                    create_name,
                    _create_item_args(_tool(tools, create_name), task),
                )
                created_keys = []
                for value in _json_from_content(created):
                    created_keys.extend(_item_keys(value))
                if not created_keys:
                    raise MCPError("create_item succeeded but returned no item key")
                item_key = created_keys[0]
                with _serve_local_pdf(pdf_path) as url:
                    result = client.call_tool(
                        import_url_name,
                        _import_url_args(
                            _tool(tools, import_url_name),
                            url,
                            task,
                            item_key=item_key,
                        ),
                    )
                operation = "created-item-and-imported-local-pdf"
            else:
                raise MCPError(
                    "no compatible local-file import or create_item + "
                    "import_attachment_url tool combination is available"
                )

        verify_query = str(task.get("doi") or task.get("title") or "")
        verified_key, _ = _search(
            client,
            tools,
            search_name,
            verify_query,
        )
        updated["state"] = "zotero-complete" if verified_key else "zotero-write-unverified"
        updated["zotero_operation"] = operation
        updated["zotero_item_key"] = verified_key or item_key
        updated["zotero_error"] = ""
        updated["zotero_result"] = _json_from_content(result)[:2]
        return updated
    except MCPError as exc:
        updated["state"] = "zotero-failed"
        updated["zotero_error"] = str(exc)
        return updated


def run(
    handoff_path: Path,
    output_dir: Path,
    *,
    url: str,
    execute: bool,
    max_tasks: int,
) -> dict[str, Any]:
    tasks = read_jsonl(handoff_path)
    client = MCPHTTPClient(url)
    client.initialize()
    tools = client.list_tools()
    search_name = _tool_name(tools, SEARCH_ALIASES)
    attach_name = _tool_name(tools, ATTACH_ALIASES)
    add_name = _tool_name(tools, ADD_ALIASES)
    create_name = _tool_name(tools, CREATE_ITEM_ALIASES)
    import_url_name = _tool_name(tools, IMPORT_URL_ALIASES)
    selected = tasks[:max_tasks] if max_tasks > 0 else tasks
    remainder = tasks[len(selected) :]
    if not search_name:
        raise MCPError(
            "Zotero MCP is connected but no supported library-search tool was found; "
            f"available={[tool.get('name') for tool in tools]}"
        )

    if execute:
        updated = [
            execute_task(
                task,
                client=client,
                tools=tools,
                search_name=search_name,
                attach_name=attach_name,
                add_name=add_name,
                create_name=create_name,
                import_url_name=import_url_name,
            )
            for task in selected
        ]
    else:
        updated = [
            {
                **task,
                "state": "zotero-dry-run",
                "zotero_error": "",
            }
            for task in selected
        ]
    updated.extend(remainder)
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / "zotero-handoff.executed.jsonl"
    write_jsonl(output, updated)
    states: dict[str, int] = {}
    for task in updated:
        state = str(task.get("state") or "unknown")
        states[state] = states.get(state, 0) + 1
    summary = {
        "tasks": len(updated),
        "execute": execute,
        "states": states,
        "tools": {
            "search": search_name,
            "attach": attach_name,
            "add": add_name,
            "create_item": create_name,
            "import_attachment_url": import_url_name,
        },
        "available_tools": [tool.get("name") for tool in tools],
        "output": str(output),
    }
    (output_dir / "zotero-execution-summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("handoff", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--url", default="http://127.0.0.1:23120/mcp")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--max-tasks", type=int, default=20)
    args = parser.parse_args()
    summary = run(
        args.handoff,
        args.output_dir,
        url=args.url,
        execute=args.execute,
        max_tasks=args.max_tasks,
    )
    print(json.dumps(summary, ensure_ascii=False))
    return 2 if summary["states"].get("zotero-failed") else 0


if __name__ == "__main__":
    raise SystemExit(main())
