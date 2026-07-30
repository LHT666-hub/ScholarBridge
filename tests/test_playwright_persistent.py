from __future__ import annotations

import http.server
import sys
import tempfile
import threading
import unittest
import urllib.parse
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from playwright_persistent_client import (  # noqa: E402
    PlaywrightPersistentClient,
    _default_chrome,
    playwright_available,
)
from run_authorized_browser import run  # noqa: E402


PDF = b"%PDF-1.4\n" + (b"0" * 700) + b"\n%%EOF\n"


class LoginDownloadHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        authenticated = "scholarbridge_session=valid" in self.headers.get(
            "Cookie", ""
        )
        if self.path == "/login":
            self._html(
                """
                <form method="post" action="/login">
                  <input aria-label="Account" name="account">
                  <button type="submit">Sign in</button>
                </form>
                """
            )
        elif self.path == "/article" and authenticated:
            self._html('<a href="/paper.pdf">PDF Download</a>')
        elif self.path == "/article":
            self.send_response(302)
            self.send_header("Location", "/login")
            self.end_headers()
        elif self.path == "/paper.pdf" and authenticated:
            self.send_response(200)
            self.send_header("Content-Type", "application/pdf")
            self.send_header(
                "Content-Disposition",
                'attachment; filename="persistent-session.pdf"',
            )
            self.send_header("Content-Length", str(len(PDF)))
            self.end_headers()
            self.wfile.write(PDF)
        else:
            self.send_error(404)

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        fields = urllib.parse.parse_qs(
            self.rfile.read(length).decode("utf-8")
        )
        if self.path == "/login" and fields.get("account") == ["researcher"]:
            self.send_response(302)
            self.send_header(
                "Set-Cookie",
                "scholarbridge_session=valid; Path=/; Max-Age=3600; SameSite=Lax",
            )
            self.send_header("Location", "/article")
            self.end_headers()
        else:
            self.send_error(403)

    def _html(self, body: str) -> None:
        data = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format: str, *args: object) -> None:
        return


@unittest.skipUnless(
    playwright_available() and _default_chrome() is not None,
    "Python Playwright or installed Chrome is unavailable",
)
class PlaywrightPersistentTests(unittest.TestCase):
    def test_login_cookie_survives_restart_and_downloads_pdf(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            profile = root / "profile"
            downloads = root / "downloads"
            server = http.server.ThreadingHTTPServer(
                ("127.0.0.1", 0),
                LoginDownloadHandler,
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = f"http://127.0.0.1:{server.server_address[1]}"
            try:
                first = PlaywrightPersistentClient(
                    profile_dir=profile,
                    download_dir=downloads,
                    headless=True,
                )
                first.navigate(f"{base}/login", new_tab=False)
                tree = first.snapshot()["tree"]
                self.assertIn('textbox "Account" @e0', tree)
                self.assertIn('button "Sign in" @e1', tree)
                first.fill("@e0", "researcher")
                first.click("@e1")
                first._active_page().wait_for_url(f"{base}/article")
                first.close()

                queue = root / "queue.jsonl"
                queue.write_text(
                    (
                        '{"record_id":"1","title":"Persistent session test",'
                        f'"start_url":"{base}/article","state":"queued"}}\n'
                    ),
                    encoding="utf-8",
                )
                output = root / "out"
                summary = run(
                    queue,
                    downloads,
                    output,
                    execute=True,
                    backend="playwright",
                    base_url="http://127.0.0.1:10086",
                    session="unused",
                    profile_dir=profile,
                    chrome_executable=None,
                    headless=True,
                    max_records=1,
                    download_timeout=5,
                    settle_seconds=0,
                    start_daemon=False,
                )
                self.assertEqual(
                    summary["states"]["browser-download-complete"],
                    1,
                )
                target = downloads / "persistent-session.pdf"
                self.assertTrue(target.is_file())
                self.assertEqual(target.read_bytes(), PDF)
            finally:
                server.shutdown()
                thread.join(timeout=2)
                server.server_close()


if __name__ == "__main__":
    unittest.main()
