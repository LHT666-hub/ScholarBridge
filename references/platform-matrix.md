# Platform matrix

## Contents

- Open PDF sources
- Discovery and metadata sources
- Institution-authorized sources
- Unsupported automation

## Open PDF sources

| Source | Role | PDF behavior | ScholarBridge adapter |
|---|---|---|---|
| CORE | OA aggregator | Returns repository full-text links when available | `core` |
| Unpaywall | OA resolver | Returns legal OA PDF or landing-page locations | `unpaywall` |
| arXiv | Preprint repository | Stable per-record PDF route | `arxiv` |
| PMC OA Subset | Biomedical OA repository | Official PDF links and bulk datasets | `pmc` |
| Europe PMC | Life-science discovery/OA | Resolves DOI to open PMCID, then uses PMC | `europe-pmc` |
| OpenAlex | Scholarly graph and OA locations | Returns PDF URLs for some works; API key required | `openalex` |
| DOAJ | OA journal directory | Usually returns publisher full-text or landing links | `doaj` |
| Zenodo/institutional repositories | General repositories | Direct files vary by record | direct URL now; dedicated adapter later |

## Discovery and metadata sources

| Source | Use | Do not claim |
|---|---|---|
| Google Scholar | Human/browser-assisted discovery, versions, citations | No official bulk API; not a PDF warehouse |
| Crossref | DOI metadata normalization | Metadata hit is not PDF success |
| OpenCitations | Citation graph | Does not provide article PDFs |
| PubMed | Biomedical citations and abstracts | PubMed is not PMC full text |
| Scopus / Web of Science | Licensed discovery and exports | Do not automate PDF download through indexes |
| SciFinder | Specialist index | Do not assume it hosts article PDF |

## Institution-authorized sources

| Type | Examples | Handling |
|---|---|---|
| Publisher platforms | ScienceDirect, Springer Nature, Wiley, IEEE, ACS, RSC | User-authenticated visible browser; respect license and TDM rules |
| Chinese full-text platforms | CNKI, Wanfang, CQVIP | User performs login, CAPTCHA and native download |
| Authentication gateways | CARSI, WebVPN, EZproxy, OpenAthens, Shibboleth | Authentication entry only; never collect credentials |
| Library discovery systems | Primo, Summon and local portals | Resolve to the actual provider and record provenance |

## Unsupported automation

- Google Scholar unattended scraping or CAPTCHA bypass.
- Publisher paywall circumvention.
- Credential, session-cookie or token collection.
- DRM removal or hidden-interface discovery.
- Proxy rotation intended to evade rate limits.
- Treating campus access as permission for unlimited automated retrieval.
