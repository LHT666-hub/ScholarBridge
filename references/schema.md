# Output schema

## `manifest.csv`

| Field | Meaning |
|---|---|
| `record_id` | Stable local identifier |
| `title` | Normalized title |
| `doi` | Lower-case normalized DOI |
| `arxiv_id` | arXiv identifier |
| `pmcid` | PubMed Central identifier |
| `status` | `downloaded`, `duplicate`, `no_open_pdf`, `failed`, or `dry_run` |
| `provider` | Successful provider |
| `license` | Provider-reported license when available |
| `version` | Published, accepted, submitted or unknown |
| `pdf_path` | Local validated PDF path |
| `sha256` | Content hash |
| `resolved_url` | Final network URL |
| `attempt_count` | Number of attempted candidates |
| `reason` | Failure or dry-run explanation |

## `plan.jsonl`

Each line contains:

```json
{
  "record": {},
  "candidates": [],
  "discovery_errors": []
}
```

Candidate fields are `provider`, `url`, `landing_page`, `license`, `version`, and `note`.

## `attempts.jsonl`

Each line records one actual candidate attempt:

```json
{
  "record_id": "abc123",
  "provider": "pmc",
  "url": "https://...",
  "status": "downloaded",
  "error": ""
}
```

## `authorized-queue.browser.jsonl`

`run_authorized_browser.py` adds browser execution fields to each authorized queue row:

| Field | Meaning |
|---|---|
| `state` | Browser result such as `browser-download-complete`, `needs-user-authentication`, `needs-manual-browser-step`, `download-clicked-no-file`, or `stopped-platform-warning` |
| `downloaded_filename` | Completed PDF filename observed in the browser download directory |
| `browser_backend` | `webbridge` or `playwright` for rows actually executed |
| `browser_error` | Concrete stop or failure reason |
| `snapshot_excerpt` | Bounded accessibility-tree excerpt when a manual step is needed |

## `zotero-handoff.executed.jsonl`

`execute_zotero_handoff.py` adds:

| Field | Meaning |
|---|---|
| `state` | `zotero-complete`, `zotero-write-unverified`, `zotero-failed`, or `zotero-dry-run` |
| `zotero_operation` | `attached-to-existing` or `created-from-file` |
| `zotero_item_key` | Item key found after the write |
| `zotero_error` | MCP transport, schema mapping, tool, or verification failure |
