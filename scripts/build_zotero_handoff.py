#!/usr/bin/env python3
"""Build an auditable Zotero MCP handoff from an ingestion manifest."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

from common import write_jsonl


def run(manifest_path: Path, output_dir: Path, collection: str = "") -> dict[str, Any]:
    with manifest_path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    tasks = []
    for row in rows:
        if row.get("status") not in {"ingested", "duplicate"} or not row.get("pdf_path"):
            continue
        tasks.append(
            {
                "task_id": f"zotero-{row.get('record_id', '')}",
                "record_id": row.get("record_id", ""),
                "title": row.get("title", ""),
                "doi": row.get("doi", ""),
                "authors": row.get("authors", ""),
                "year": row.get("year", ""),
                "source": row.get("source", ""),
                "pdf_path": str(Path(row["pdf_path"]).resolve()),
                "sha256": row.get("sha256", ""),
                "collection": collection,
                "operation": "upsert-pdf-attachment",
                "dedupe_order": ["doi", "normalized-title", "sha256"],
                "preferred_backend": "zotero-mcp",
                "preferred_tools": {
                    "find_existing": "search library by DOI, then exact title",
                    "new_item": "zotero_add_from_file",
                    "existing_item": "zotero_attach_file",
                    "collection": "create/find collection, then add item",
                },
                "state": "awaiting-zotero-agent",
            }
        )
    output_dir.mkdir(parents=True, exist_ok=True)
    write_jsonl(output_dir / "zotero-handoff.jsonl", tasks)
    body = f"""# Zotero import handoff

Prepared {len(tasks)} validated PDF task(s).

For each row in `zotero-handoff.jsonl`:

1. Keep Zotero Desktop running.
2. Search the library by DOI, then exact normalized title.
3. If an item exists, attach the local file with `zotero_attach_file`.
4. Otherwise import the local PDF with `zotero_add_from_file`, then reconcile metadata.
5. Add the item to `{collection or 'the user-selected collection'}` when requested.
6. Confirm the attachment exists before marking the task complete.
7. Do not delete the archived source PDF automatically.

If those MCP tools are unavailable, use Zotero Connector or drag the validated PDF into
Zotero and run Retrieve Metadata for PDF. Report the fallback instead of claiming an
automatic import.
"""
    (output_dir / "zotero-handoff.md").write_text(body, encoding="utf-8")
    summary = {
        "tasks": len(tasks),
        "output": str(output_dir / "zotero-handoff.jsonl"),
        "backend": "zotero-mcp-handoff",
    }
    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--collection", default="")
    args = parser.parse_args()
    print(json.dumps(run(args.manifest, args.output_dir, args.collection), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

