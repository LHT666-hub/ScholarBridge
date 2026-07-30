from __future__ import annotations

import http.server
import json
import sys
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from execute_zotero_handoff import run  # noqa: E402


PDF = b"%PDF-1.4\n" + (b"0" * 700) + b"\n%%EOF\n"


class ZoteroMCPHandler(http.server.BaseHTTPRequestHandler):
    added = False

    def _tool_result(self, name: str, arguments: dict[str, object]) -> dict[str, object]:
        if name == "search_library":
            items = [{"key": "ITEM123"}] if self.added else []
            return {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps({"items": items}),
                    }
                ]
            }
        if name == "create_item":
            self.__class__.added = True
            return {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps({"key": "ITEM123", "created": True}),
                    }
                ]
            }
        if name == "import_attachment_url":
            with urllib.request.urlopen(str(arguments["url"]), timeout=3) as response:
                self.assert_pdf = response.read().startswith(b"%PDF-")
            return {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(
                            {
                                "key": "ATTACH123",
                                "parentItemKey": arguments.get("parentItemKey"),
                                "imported": self.assert_pdf,
                            }
                        ),
                    }
                ]
            }
        return {"content": [{"type": "text", "text": "{}"}]}

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        method = payload["method"]
        request_id = payload.get("id")
        if method == "initialize":
            result: dict[str, object] = {
                "protocolVersion": "2025-03-26",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "fake-zotero", "version": "1"},
            }
        elif method == "tools/list":
            result = {
                "tools": [
                    {
                        "name": "search_library",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "query": {"type": "string"},
                                "limit": {"type": "integer"},
                            },
                            "required": ["query"],
                        },
                    },
                    {
                        "name": "create_item",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "itemType": {"type": "string"},
                                "fields": {"type": "object"},
                                "creators": {"type": "array"},
                            },
                            "required": ["itemType"],
                        },
                    },
                    {
                        "name": "import_attachment_url",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "url": {"type": "string"},
                                "parentItemKey": {"type": "string"},
                                "title": {"type": "string"},
                                "contentType": {"type": "string"},
                                "ifExists": {"type": "string"},
                            },
                            "required": ["url"],
                        },
                    },
                ]
            }
        elif method == "tools/call":
            result = self._tool_result(
                str(payload["params"]["name"]),
                payload["params"].get("arguments", {}),
            )
        else:
            result = {}
        if request_id is None:
            self.send_response(202)
            self.end_headers()
            return
        data = json.dumps(
            {"jsonrpc": "2.0", "id": request_id, "result": result}
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Mcp-Session-Id", "test-session")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format: str, *args: object) -> None:
        return


class ZoteroExecutionTests(unittest.TestCase):
    def test_new_pdf_is_added_and_verified(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            pdf = root / "paper.pdf"
            pdf.write_bytes(PDF)
            handoff = root / "handoff.jsonl"
            handoff.write_text(
                json.dumps(
                    {
                        "task_id": "zotero-1",
                        "record_id": "1",
                        "title": "测试论文",
                        "doi": "10.1234/test",
                        "pdf_path": str(pdf),
                        "collection": "ScholarBridge",
                        "state": "awaiting-zotero-agent",
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            ZoteroMCPHandler.added = False
            server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), ZoteroMCPHandler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                output = root / "out"
                summary = run(
                    handoff,
                    output,
                    url=f"http://127.0.0.1:{server.server_address[1]}/mcp",
                    execute=True,
                    max_tasks=20,
                )
                self.assertEqual(summary["states"]["zotero-complete"], 1)
                row = json.loads(
                    (output / "zotero-handoff.executed.jsonl").read_text(
                        encoding="utf-8"
                    )
                )
                self.assertEqual(row["zotero_item_key"], "ITEM123")
                self.assertEqual(
                    row["zotero_operation"],
                    "created-item-and-imported-local-pdf",
                )
            finally:
                server.shutdown()
                thread.join(timeout=2)
                server.server_close()


if __name__ == "__main__":
    unittest.main()
