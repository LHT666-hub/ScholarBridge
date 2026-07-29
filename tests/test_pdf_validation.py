from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from common import UnsafeUrlError, validate_pdf, validate_public_url  # noqa: E402


def fake_pdf() -> bytes:
    return b"%PDF-1.4\n" + (b"0" * 700) + b"\n%%EOF\n"


class PdfValidationTests(unittest.TestCase):
    def test_valid_pdf(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "paper.pdf"
            path.write_bytes(fake_pdf())
            result = validate_pdf(path)
            self.assertTrue(result["valid"])
            self.assertEqual(len(result["sha256"]), 64)

    def test_html_is_not_pdf(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "paper.pdf"
            path.write_bytes(b"<html>" + (b"x" * 700) + b"</html>")
            self.assertFalse(validate_pdf(path)["valid"])

    def test_private_url_is_refused(self) -> None:
        with self.assertRaises(UnsafeUrlError):
            validate_public_url("http://127.0.0.1/private")


if __name__ == "__main__":
    unittest.main()
