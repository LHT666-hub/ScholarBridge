# Acquisition routes and reference implementations

## Contents

- Route overview
- How login state actually works
- Reference projects and their limits
- ScholarBridge design choices

## Route overview

| Route | Best for | Technical mechanism | ScholarBridge status |
|---|---|---|---|
| Open-access resolvers | DOI/PMCID/arXiv lists | Official APIs and public PDF URLs | Implemented |
| Official bulk tools | Large OA corpora | Provider CLI, snapshots, checkpoints | External adapter/documented |
| Zotero Connector translators | Metadata and accessible attachments | Site translator runs in the browser and passes items to Zotero | External dependency/documented |
| Existing logged-in browser | CNKI, Wanfang, CQVIP, publishers | Agent controls the user's visible Chrome tab and native download button | WebBridge runner implemented; local mock regression passed |
| Dedicated persistent browser | A platform-specific repeatable workflow | Playwright persistent profile stores browser session data | Runner implemented; real local Chrome persistence/download test passed |
| Download-folder intake | Any authorized native browser download | Validate, match, hash, copy, and generate Zotero tasks | Implemented |
| Zotero ingestion | Validated local PDFs | Zotero MCP attaches/imports files and reconciles metadata | MCP handoff implemented |

## How login state actually works

Closed databases do not become open APIs after installing a Skill. The user still needs
a valid institution, VPN, library gateway, or personal subscription.

There are three common session designs:

### Existing browser session

Kimi WebBridge and the Playwright MCP browser-extension mode connect to a real local
Chrome profile or an already-open tab. The user logs in normally. The database's own
cookies, local storage, SSO redirects, and institution state remain inside Chrome.

This does **not** simulate credentials and does not require ScholarBridge to copy a
password or Cookie file. It is the preferred general route.

### Dedicated persistent profile

Playwright can launch a visible persistent browser context with a dedicated
`user-data-dir`. The user completes login, and the browser profile preserves durable
cookies and local storage for later runs. Session-only cookies may disappear after the
browser closes, while expired SSO state still requires the user to log in again.
`wuruiqi/cnki-mcp` uses this general pattern for CNKI.

This is convenient for a platform-specific adapter, but the profile directory becomes
sensitive and must not be committed or shared.

### Explicit Cookie export

Some tools serialize selected cookies to JSON and re-inject them later.
`wuruiqi/cnki-mcp` additionally supports this approach. It works, but the Cookie file is
a bearer credential and may expose institution access. ScholarBridge does not export
or store cookies.

In every design, CAPTCHA and institutional login remain human checkpoints. A safe
workflow pauses and lets the user solve them in the visible browser; it never solves or
bypasses them automatically.

## Reference projects and their limits

### OpenAlex official CLI

Repository: <https://github.com/ourresearch/openalex-official>

- Accepts OpenAlex IDs, DOIs, or filters.
- Downloads OA PDFs/TEI with concurrency, checkpointing, resume, and rate control.
- Appropriate for high-volume **open** retrieval.
- Requires an OpenAlex API key and does not unlock subscription PDFs.

ScholarBridge keeps its own bounded resolver for small mixed lists and recommends the
official CLI for high-volume OpenAlex jobs.

### pygetpapers and paperscraper

Repositories:

- <https://github.com/petermr/pygetpapers>
- <https://github.com/jannisborn/paperscraper>

These tools query open repositories such as Europe PMC, arXiv, bioRxiv, and medRxiv,
then save full text and metadata. They demonstrate modular repository adapters,
restart/update behavior, and corpus-oriented output. Coverage and full-text formats
vary by provider; they do not solve CNKI or publisher authentication.

### Zotero Chinese translators

Repository: <https://github.com/l0o0/translators_CN>

The CNKI and Wanfang translators parse list/detail pages and add metadata plus a PDF
attachment URL when the page exposes one. CQVIP's current translator primarily imports
metadata; its PDF attachment block is disabled. Translator success still depends on
site structure, access rights, Zotero Connector, and whether the browser can fetch the
attachment.

The repository is AGPL-3.0. ScholarBridge treats it as an external dependency and does
not copy its source into this project.

### cnki-mcp

Repository: <https://github.com/wuruiqi/cnki-mcp>

Technical path:

1. Launch a visible Playwright persistent browser profile.
2. Let the user complete institution login.
3. Preserve session state in the profile and optionally a CNKI Cookie JSON file.
4. Parse CNKI result/detail pages.
5. Click the visible PDF/CAJ control and capture Playwright's native download event.
6. Send metadata to Zotero's local Connector on `127.0.0.1:23119`.
7. Upload the local PDF bytes as a child attachment.

Strengths:

- It closes the CNKI → PDF → Zotero loop.
- It has explicit CAPTCHA pause and PDF-to-item association.

Limits:

- CNKI-specific selectors and 2026 page assumptions can break after site changes.
- The documented result count is constrained by incomplete pagination.
- Cookie JSON is sensitive.
- The source currently includes an automation-detection-disabling browser flag.
  ScholarBridge does not adopt that flag or any evasion behavior.

### Selenium remote-debugging CNKI downloader

Repository:
<https://github.com/fahaxiki4/CNKI-China-National-Knowledge-Infrastructure-Thesis-Automatic-Download-Tool>

It launches Edge with remote debugging, attaches Selenium to the real Edge user-data
directory, pauses for manual login, and sets the browser download directory. This
proves that an existing local login can be reused without entering credentials into an
Agent. The repository also contains stealth and human-mimicry code, which ScholarBridge
does not adopt.

### Kimi WebBridge and Playwright MCP

- Kimi WebBridge controls a real local Chrome through a local daemon and extension.
- Microsoft Playwright MCP can use a persistent profile, storage state, or browser
  extension to connect to existing tabs.

Both are browser-control transports, not literature databases. ScholarBridge supplies
the queue, stop rules, provenance, PDF validation, and post-download reconciliation.
The transport supplies clicks, navigation, and native download access.

### zotero-mcp

Repository: <https://github.com/54yyyu/zotero-mcp>

Useful write tools include adding a local PDF, attaching a file to an existing item,
creating collections, and duplicate management. ScholarBridge produces
`zotero-handoff.jsonl` so an Agent can search by DOI/title before choosing
`zotero_add_from_file` or `zotero_attach_file`.

### SciPDF / ScanSciPDF

Repository: <https://github.com/syt2/zotero-scipdf>

SciPDF is a Zotero 7/8 plug-in that writes Sci-Hub resolvers into Zotero's built-in
`extensions.zotero.findPDFs.resolvers` configuration. For an item with a DOI and no
attachment, Zotero's “Find Full Text” then queries those resolvers and attaches a
returned PDF.

This is technically a **DOI → custom resolver → Zotero attachment** route. It is not an
institution-login route, not an open-access provenance check, and may retrieve
copyrighted works without publisher authorization. ScholarBridge records it as an
ecosystem route for technical comparison but does not integrate, recommend, test, or
package Sci-Hub resolvers.

## ScholarBridge design choices

ScholarBridge combines the compliant parts of these projects:

1. Resolve open copies first.
2. Route high-volume OA work to official bulk tools.
3. For subscription platforms, reuse a visible browser login without collecting
   credentials.
4. Require native download controls and stop on access warnings.
5. Treat the browser download directory as an untrusted inbox.
6. Validate `%PDF-`, size, `%%EOF`, and SHA-256 before archiving.
7. Match each file back to a queue record and preserve provenance.
8. Search Zotero before importing or attaching the validated PDF.

The result is a cross-platform protocol rather than a fragile universal scraper.
ScholarBridge now implements both the existing-Chrome WebBridge transport and an
independent Playwright persistent-profile transport. It does not implement Cookie JSON
export.
