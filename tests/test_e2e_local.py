from __future__ import annotations

import csv
import http.server
import socketserver
import sys
import tempfile
import threading
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from fetch_open_pdfs import run  # noqa: E402


PDF = b"%PDF-1.4\n" + (b"0" * 700) + b"\n%%EOF\n"


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/landing":
            body = b'<html><meta name="citation_pdf_url" content="/paper.pdf"></html>'
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path == "/paper.pdf":
            self.send_response(200)
            self.send_header("Content-Type", "application/pdf")
            self.send_header("Content-Length", str(len(PDF)))
            self.end_headers()
            self.wfile.write(PDF)
            return
        self.send_error(404)

    def log_message(self, *_: object) -> None:
        return


class E2ETests(unittest.TestCase):
    def test_html_landing_resolves_and_downloads_pdf(self) -> None:
        with socketserver.TCPServer(("127.0.0.1", 0), Handler) as server:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            with tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                input_path = root / "input.csv"
                input_path.write_text(
                    f"title,pdf_url\nLocal test,http://127.0.0.1:{server.server_address[1]}/landing\n",
                    encoding="utf-8",
                )
                summary = run(
                    input_path,
                    root / "output",
                    execute=True,
                    email="",
                    provider_names=["direct"],
                    openalex_api_key="",
                    core_api_key="",
                    max_records=10,
                    max_mb=5,
                    timeout=5,
                    delay=0,
                    allow_private=True,
                )
                self.assertEqual(summary["downloaded"], 1)
                with (root / "output" / "manifest.csv").open(
                    "r", encoding="utf-8-sig", newline=""
                ) as handle:
                    row = next(csv.DictReader(handle))
                self.assertEqual(row["status"], "downloaded")
                self.assertTrue(Path(row["pdf_path"]).exists())

                resumed = run(
                    input_path,
                    root / "output",
                    execute=True,
                    email="",
                    provider_names=["direct"],
                    openalex_api_key="",
                    core_api_key="",
                    max_records=10,
                    max_mb=5,
                    timeout=5,
                    delay=0,
                    allow_private=True,
                    resume=True,
                )
                self.assertEqual(resumed["resumed"], 1)
                self.assertEqual(resumed["unresolved"], 0)
            server.shutdown()


if __name__ == "__main__":
    unittest.main()
