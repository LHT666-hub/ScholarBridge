from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from common import Record  # noqa: E402
from providers import (  # noqa: E402
    openalex_candidates,
    pmc_candidates,
    resolve_doi_with_crossref,
    unpaywall_candidates,
)


class ProviderTests(unittest.TestCase):
    def test_pmc_pdf_link_is_converted_to_https(self) -> None:
        xml = b"""<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">
        <CommonPrefixes><Prefix>PMC1.1/</Prefix></CommonPrefixes>
        </ListBucketResult>"""
        metadata = {
            "is_pmc_openaccess": True,
            "license_code": "CC BY",
            "version": 1,
            "pdf_url": "s3://pmc-oa-opendata/PMC1.1/PMC1.1.pdf?md5=abc",
        }
        record = Record(record_id="1", pmcid="PMC1")
        with patch(
            "providers.request_bytes",
            return_value=(xml, "text/xml", "https://example"),
        ), patch("providers.request_json", return_value=metadata):
            candidates = pmc_candidates(record)
        self.assertEqual(candidates[0].provider, "pmc")
        self.assertEqual(candidates[0].license, "CC BY")
        self.assertTrue(candidates[0].url.startswith("https://pmc-oa-opendata.s3.amazonaws.com/"))

    def test_unpaywall_prefers_pdf_url(self) -> None:
        payload = {
            "best_oa_location": {
                "url_for_pdf": "https://repo.example/paper.pdf",
                "url_for_landing_page": "https://repo.example/item",
                "license": "cc-by",
                "version": "acceptedVersion",
            },
            "oa_locations": [],
        }
        record = Record(record_id="1", doi="10.1234/example")
        with patch("providers.request_json", return_value=payload):
            candidates = unpaywall_candidates(record, email="test@example.org")
        self.assertEqual(candidates[0].url, "https://repo.example/paper.pdf")
        self.assertEqual(candidates[0].license, "cc-by")

    def test_openalex_requires_key(self) -> None:
        record = Record(record_id="1", doi="10.1234/example")
        self.assertEqual(openalex_candidates(record), [])

    def test_crossref_title_resolution_is_conservative(self) -> None:
        payload = {
            "message": {
                "items": [
                    {
                        "DOI": "10.1234/EXACT",
                        "title": ["A Precise Scholarly Title"],
                    }
                ]
            }
        }
        record = Record(record_id="1", title="A Precise Scholarly Title")
        with patch("providers.request_json", return_value=payload):
            resolved, audit = resolve_doi_with_crossref(record)
        self.assertEqual(resolved.doi, "10.1234/exact")
        self.assertEqual(audit["status"], "resolved")


if __name__ == "__main__":
    unittest.main()
