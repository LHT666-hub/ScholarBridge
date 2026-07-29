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
