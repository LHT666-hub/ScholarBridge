from __future__ import annotations

import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from build_zotero_handoff import run as build_zotero_handoff  # noqa: E402
from ingest_downloads import run as ingest_downloads  # noqa: E402
from prepare_authorized_queue import run as prepare_queue  # noqa: E402
from prepare_authorized_queue import queue_row  # noqa: E402
from common import Record  # noqa: E402


PDF = b"%PDF-1.4\n" + (b"0" * 700) + b"\n%%EOF\n"


class AuthorizedPipelineTests(unittest.TestCase):
    def test_licensed_indexes_are_discovery_routes_not_pdf_hosts(self) -> None:
        for source, url, platform in (
            ("Web of Science", "https://www.webofscience.com/", "web-of-science"),
            ("Scopus", "https://www.scopus.com/pages/home", "scopus"),
        ):
            with self.subTest(platform=platform):
                row = queue_row(
                    Record(
                        record_id=f"id-{platform}",
                        title="Example article",
                        url=url,
                        source=source,
                    )
                )
                self.assertEqual(row["platform"], platform)
                self.assertEqual(row["state"], "discovery-export-only")
                self.assertEqual(row["route"], "licensed-discovery")
                self.assertEqual(row["access_class"], "licensed-index")

    def test_cnki_queue_download_ingest_and_zotero_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            input_path = root / "input.csv"
            input_path.write_text(
                "title,url,source\n"
                "平台治理研究,https://kns.cnki.net/kcms2/article/abstract?v=test,CNKI\n",
                encoding="utf-8",
            )
            queue_dir = root / "queue"
            summary = prepare_queue(input_path, queue_dir)
            self.assertEqual(summary["actionable"], 1)
            queue = [
                json.loads(line)
                for line in (queue_dir / "authorized-queue.jsonl").read_text(
                    encoding="utf-8"
                ).splitlines()
            ]
            self.assertEqual(queue[0]["platform"], "cnki")
            self.assertNotIn("cookie", json.dumps(queue[0]).lower())

            downloads = root / "downloads"
            downloads.mkdir()
            (downloads / queue[0]["target_filename"]).write_bytes(PDF)
            ingest_dir = root / "ingest"
            ingest = ingest_downloads(
                queue_dir / "authorized-queue.jsonl", downloads, ingest_dir
            )
            self.assertEqual(ingest["ingested"], 1)

            with (ingest_dir / "ingest-manifest.csv").open(
                "r", encoding="utf-8-sig", newline=""
            ) as handle:
                row = next(csv.DictReader(handle))
            self.assertEqual(row["status"], "ingested")
            self.assertTrue(Path(row["pdf_path"]).exists())

            zotero_dir = root / "zotero"
            zotero = build_zotero_handoff(
                ingest_dir / "ingest-manifest.csv", zotero_dir, "测试收藏夹"
            )
            self.assertEqual(zotero["tasks"], 1)
            handoff = json.loads(
                (zotero_dir / "zotero-handoff.jsonl").read_text(encoding="utf-8")
            )
            self.assertEqual(handoff["operation"], "upsert-pdf-attachment")
            self.assertEqual(handoff["collection"], "测试收藏夹")

    def test_partial_and_html_disguised_as_pdf_are_not_ingested(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            queue = root / "queue.jsonl"
            queue.write_text(
                json.dumps(
                    {
                        "record_id": "abc",
                        "title": "Example",
                        "target_filename": "Example.pdf",
                        "platform": "publisher-or-library",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            downloads = root / "downloads"
            downloads.mkdir()
            (downloads / "Example.pdf").write_text("<html>login</html>", encoding="utf-8")
            (downloads / "Other.pdf.crdownload").write_bytes(b"partial")
            summary = ingest_downloads(queue, downloads, root / "out")
            self.assertEqual(summary["ingested"], 0)
            self.assertEqual(summary["invalid"], 1)
            self.assertEqual(len(summary["partial_downloads"]), 1)


if __name__ == "__main__":
    unittest.main()
