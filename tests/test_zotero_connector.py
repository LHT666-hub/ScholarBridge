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

from zotero_connector_client import ZoteroConnectorClient  # noqa: E402


PDF = b"%PDF-1.4\n" + (b"0" * 700) + b"\n%%EOF\n"


class ConnectorHandler(http.server.BaseHTTPRequestHandler):
    item = {}
    attachment = b""
    metadata = {}

    def do_GET(self) -> None:  # noqa: N802
        self.send_response(200 if self.path.endswith("/ping") else 404)
        self.end_headers()

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        if self.path.endswith("/saveItems"):
            self.__class__.item = json.loads(body.decode("utf-8"))["items"][0]
            self.send_response(201)
        elif self.path.endswith("/saveAttachment"):
            self.__class__.attachment = body
            self.__class__.metadata = json.loads(self.headers["X-Metadata"])
            self.send_response(200)
        else:
            self.send_response(404)
        self.end_headers()

    def log_message(self, format: str, *args: object) -> None:
        return


class ZoteroConnectorTests(unittest.TestCase):
    def test_create_item_and_upload_pdf(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            pdf = root / "论文.pdf"
            pdf.write_bytes(PDF)
            server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), ConnectorHandler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                client = ZoteroConnectorClient(
                    f"http://127.0.0.1:{server.server_address[1]}/connector"
                )
                self.assertTrue(client.ping())
                result = client.create_item_with_pdf(
                    {
                        "title": "测试论文",
                        "authors": "Zhang, San; Li Si",
                        "year": "2026",
                        "doi": "10.1234/test",
                        "pdf_path": str(pdf),
                    }
                )
                self.assertEqual(result["save_attachment_status"], 200)
                self.assertEqual(ConnectorHandler.item["title"], "测试论文")
                self.assertTrue(ConnectorHandler.attachment.startswith(b"%PDF-"))
                self.assertEqual(
                    ConnectorHandler.metadata["parentItemID"],
                    ConnectorHandler.item["id"],
                )
            finally:
                server.shutdown()
                thread.join(timeout=2)
                server.server_close()


if __name__ == "__main__":
    unittest.main()
