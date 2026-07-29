from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from normalize_records import normalize_file  # noqa: E402


class NormalizeTests(unittest.TestCase):
    def test_csv_normalizes_and_deduplicates_doi(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "input.csv"
            path.write_text(
                "title,doi\nOne,https://doi.org/10.1234/ABC.1\nDuplicate,doi:10.1234/abc.1\n",
                encoding="utf-8",
            )
            accepted, duplicates, rejected = normalize_file(path)
            self.assertEqual(accepted[0].doi, "10.1234/abc.1")
            self.assertEqual(len(accepted), 1)
            self.assertEqual(len(duplicates), 1)
            self.assertEqual(rejected, [])

    def test_text_recognizes_arxiv_and_pmc(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "input.txt"
            path.write_text(
                "https://arxiv.org/abs/1706.03762\nPMC5334499\n",
                encoding="utf-8",
            )
            accepted, _, _ = normalize_file(path)
            self.assertEqual(accepted[0].arxiv_id, "1706.03762")
            self.assertEqual(accepted[1].pmcid, "PMC5334499")

    def test_google_scholar_endnote_export(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "scholar.enw"
            path.write_text(
                "%0 Journal Article\n%A Example, Alice\n%D 2024\n%T A Scholar Export\n"
                "%R 10.1234/EXAMPLE.2\n%U https://example.org/item\n",
                encoding="utf-8",
            )
            accepted, _, _ = normalize_file(path)
            self.assertEqual(len(accepted), 1)
            self.assertEqual(accepted[0].doi, "10.1234/example.2")
            self.assertEqual(accepted[0].title, "A Scholar Export")


if __name__ == "__main__":
    unittest.main()
