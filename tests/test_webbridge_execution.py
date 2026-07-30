from __future__ import annotations

import http.server
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from run_authorized_browser import run  # noqa: E402


PDF = b"%PDF-1.4\n" + (b"0" * 700) + b"\n%%EOF\n"


class WebBridgeHandler(http.server.BaseHTTPRequestHandler):
    download_dir: Path

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        action = payload["action"]
        if action == "navigate":
            body = {"success": True, "url": payload["args"]["url"], "tabId": 1}
        elif action == "snapshot":
            body = {
                "success": True,
                "url": "https://example.test/article",
                "title": "Article",
                "tree": '- link "PDF下载" @e9',
            }
        elif action == "click":
            (self.download_dir / "downloaded.pdf").write_bytes(PDF)
            body = {"success": True, "tag": "A", "text": "PDF下载"}
        elif action == "list_tabs":
            body = {
                "success": True,
                "tabs": [
                    {
                        "tabId": 1,
                        "url": "https://example.test/article",
                        "title": "Article",
                    }
                ],
            }
        else:
            body = {"success": True}
        data = json.dumps(body).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format: str, *args: object) -> None:
        return


class WebBridgeExecutionTests(unittest.TestCase):
    def test_visible_download_control_creates_completed_queue_item(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            downloads = root / "downloads"
            downloads.mkdir()
            WebBridgeHandler.download_dir = downloads
            server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), WebBridgeHandler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                queue = root / "queue.jsonl"
                queue.write_text(
                    json.dumps(
                        {
                            "record_id": "1",
                            "title": "测试论文",
                            "start_url": "https://example.test/article",
                            "state": "awaiting-user-authentication",
                        },
                        ensure_ascii=False,
                    )
                    + "\n",
                    encoding="utf-8",
                )
                output = root / "out"
                summary = run(
                    queue,
                    downloads,
                    output,
                    execute=True,
                    backend="webbridge",
                    base_url=f"http://127.0.0.1:{server.server_address[1]}",
                    session="test-session",
                    profile_dir=root / "profile",
                    chrome_executable=None,
                    headless=True,
                    max_records=10,
                    download_timeout=3,
                    settle_seconds=0,
                    start_daemon=False,
                )
                self.assertEqual(summary["states"]["browser-download-complete"], 1)
                row = json.loads(
                    (output / "authorized-queue.browser.jsonl").read_text(
                        encoding="utf-8"
                    )
                )
                self.assertEqual(row["downloaded_filename"], "downloaded.pdf")
            finally:
                server.shutdown()
                thread.join(timeout=2)
                server.server_close()


if __name__ == "__main__":
    unittest.main()
