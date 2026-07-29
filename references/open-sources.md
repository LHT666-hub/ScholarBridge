# Open PDF sources

## Contents

- Adapter order
- Provider details
- Metadata-only services
- Bulk snapshots
- Configuration

## Adapter order

Use the default sequence:

```text
direct → arXiv → PMC → Europe PMC → Unpaywall → OpenAlex → CORE → DOAJ
```

This sequence favors explicit identifiers and official repositories before aggregators. A provider failure does not prove that the paper is closed; continue through the remaining providers and record each attempt.

## Provider details

### CORE

- Purpose: broad open-access repository aggregation.
- API: `https://api.core.ac.uk/v3/`
- Authentication: `CORE_API_KEY`.
- Output: metadata plus direct or source full-text links when available.
- Limits: follow the current API quota and terms.
- Official documentation: <https://core.ac.uk/services/api>

### Unpaywall

- Purpose: resolve a DOI to known legal OA locations.
- API: `https://api.unpaywall.org/v2/{doi}?email={email}`
- Authentication: no key; a real contact email is required.
- Output: `best_oa_location` and other OA locations.
- Caveat: some locations expose a landing page rather than a direct PDF.
- Official product page: <https://data.unpaywall.org/products/api>

### arXiv

- Purpose: preprints in physics, mathematics, computer science and related fields.
- Per-record PDF: `https://arxiv.org/pdf/{arxiv_id}.pdf`
- Bulk: requester-pays S3 buckets; full corpus is multi-terabyte.
- Caveat: most arXiv works use the default arXiv distribution license; downloading for research is not the same as permission to redistribute a mirror.
- Official bulk guide: <https://info.arxiv.org/help/bulk_data_s3.html>

### PMC Open Access Subset

- Purpose: reusable biomedical and life-science full text.
- Discovery API: `https://www.ncbi.nlm.nih.gov/pmc/utils/oa/oa.fcgi`
- Identifier: PMCID.
- Output: official PDF or archive URLs plus license.
- Caveat: not every PMC item belongs to the OA Subset; licenses vary by article.
- Official API: <https://pmc.ncbi.nlm.nih.gov/tools/oa-service/>

### Europe PMC

- Purpose: life-science discovery, metadata, preprints and OA full text.
- Use: resolve an exact DOI to an OA PMCID, then request the official PMC PDF.
- Bulk: Europe PMC exposes OA PDF and XML downloads.
- Official downloads: <https://europepmc.org/downloads/openaccess>

### OpenAlex

- Purpose: works, authors, institutions, sources, topics and citation graph.
- Authentication: `OPENALEX_API_KEY`.
- Use: retrieve `best_oa_location` and work locations containing `pdf_url`.
- Bulk: the complete snapshot is much larger than a normal project subset; use the API or official CLI for ordinary workflows.
- Official documentation: <https://developers.openalex.org/>
- Download overview: <https://developers.openalex.org/download/overview>

### DOAJ

- Purpose: directory and metadata for open-access journals and articles.
- Use: resolve DOI to article full-text or landing links.
- Caveat: DOAJ usually indexes rather than hosts the PDF; the target site can still require HTML resolution.
- Official metadata methods: <https://doaj.org/docs/faq/>

### Zenodo and institutional repositories

- Purpose: deposited research outputs and repository manuscripts.
- Current support: accept direct PDF URLs exported by these repositories.
- Planned: dedicated Zenodo REST and generic OAI-PMH adapters.
- Do not infer that every deposited file is a PDF or that every license permits redistribution.

## Metadata-only services

Use these to discover or normalize records, not to declare PDF success:

- Crossref REST API: DOI and bibliographic metadata.
- OpenCitations: references and citations.
- PubMed: biomedical citations and abstracts.
- Google Scholar: human-facing discovery and versions.

## Bulk snapshots

Full snapshots are a separate operating mode from a paper list:

- They may be hundreds of gigabytes or multiple terabytes.
- They need resumable downloads, checksums, storage forecasts and update logic.
- Metadata snapshots do not necessarily contain PDFs.
- Obtain complete corpora only through the provider's official bulk interface and terms.

ScholarBridge's normal command is intentionally bounded by `--max-records` and `--max-mb`. Do not use it to mirror a complete repository.

## Configuration

```text
SCHOLARBRIDGE_EMAIL=researcher@example.edu
OPENALEX_API_KEY=...
CORE_API_KEY=...
```

Environment variables are optional. Without an email, Unpaywall is skipped. Without provider keys, OpenAlex and CORE are skipped. arXiv, PMC, Europe PMC and DOAJ remain available.
