from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from platform_adapters import get_platform_adapter  # noqa: E402
from probe_authorized_platforms import _choose_ref, write_report  # noqa: E402


class PlatformAdapterTests(unittest.TestCase):
    def test_observed_search_controls_are_selected(self) -> None:
        fixtures = {
            "wanfang": '- textbox "海量资源, 等你发现" [ref=@e3]\n- button "检索" [ref=@e4]',
            "cqvip": '- textbox "请输入检索词" [ref=@e7]\n- button "检索" [ref=@e8]',
            "science-direct": '- combobox "qs" [ref=@e9]\n- button "Submit quick search" [ref=@e10]',
            "ieee": '- searchbox "main" [ref=@e19]\n- button "Search" [ref=@e20]',
        }
        for platform, tree in fixtures.items():
            with self.subTest(platform=platform):
                adapter = get_platform_adapter(platform)
                self.assertIsNotNone(adapter)
                self.assertTrue(
                    _choose_ref(
                        tree,
                        adapter.search_input_terms,
                        adapter.search_input_roles,
                    )
                )
                self.assertTrue(
                    _choose_ref(tree, adapter.search_button_terms, ("button", "link"))
                )

    def test_probe_report_states_scope_honestly(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)
            rows = [
                {
                    "platform": "wanfang",
                    "role": "full-text",
                    "state": "page-readable",
                    "http_status": 200,
                    "search_input_found": True,
                    "search_button_found": True,
                    "preferred_backend": "playwright",
                }
            ]
            write_report(output, rows)
            report = (output / "platform-probe.md").read_text(encoding="utf-8")
            payload = json.loads(
                (output / "platform-probe.json").read_text(encoding="utf-8")
            )
            self.assertIn("prove subscription access or PDF download success", report)
            self.assertEqual(payload["records"][0]["state"], "page-readable")


if __name__ == "__main__":
    unittest.main()
