#!/usr/bin/env python3
"""Open-source discovery adapters that return legal PDF candidates."""

from __future__ import annotations

import urllib.parse
import xml.etree.ElementTree as ET
import re
from difflib import SequenceMatcher
from typing import Any

from common import Candidate, Record, ScholarBridgeError, normalize_doi, request_bytes, request_json


def _title_key(value: str) -> str:
    return re.sub(r"\W+", " ", value.casefold()).strip()


def resolve_doi_with_crossref(
    record: Record,
    *,
    email: str = "",
    timeout: int = 30,
    threshold: float = 0.92,
) -> tuple[Record, dict[str, Any]]:
    """Conservatively resolve a title-only record to a Crossref DOI."""
    if record.doi or not record.title:
        return record, {}
    params = {
        "query.title": record.title,
        "rows": 5,
        "select": "DOI,title,author,published",
    }
    if email:
        params["mailto"] = email
    url = "https://api.crossref.org/works?" + urllib.parse.urlencode(params)
    payload = request_json(url, email=email, timeout=timeout)
    target = _title_key(record.title)
    best: tuple[float, dict[str, Any]] | None = None
    for item in payload.get("message", {}).get("items", []):
        titles = item.get("title") or []
        title = str(titles[0] if titles else "")
        score = SequenceMatcher(None, target, _title_key(title)).ratio()
        if best is None or score > best[0]:
            best = (score, item)
    if best is None or best[0] < threshold:
        return record, {
            "provider": "crossref",
            "status": "unresolved",
            "best_score": round(best[0], 4) if best else 0,
        }
    doi = normalize_doi(best[1].get("DOI"))
    if not doi:
        return record, {
            "provider": "crossref",
            "status": "unresolved",
            "best_score": round(best[0], 4),
        }
    enriched = Record.from_dict({**record.to_dict(), "doi": doi})
    return enriched, {
        "provider": "crossref",
        "status": "resolved",
        "doi": doi,
        "score": round(best[0], 4),
    }


def direct_candidates(record: Record, **_: Any) -> list[Candidate]:
    candidates = []
    if record.pdf_url:
        candidates.append(Candidate("direct", record.pdf_url, note="PDF URL supplied by user"))
    if record.url and record.url.lower().split("?", 1)[0].endswith(".pdf"):
        candidates.append(Candidate("direct", record.url, note="PDF-like URL supplied by user"))
    return candidates


def arxiv_candidates(record: Record, **_: Any) -> list[Candidate]:
    if not record.arxiv_id:
        return []
    arxiv_id = record.arxiv_id.removesuffix(".pdf")
    return [
        Candidate(
            "arxiv",
            f"https://arxiv.org/pdf/{urllib.parse.quote(arxiv_id, safe='/')}.pdf",
            landing_page=f"https://arxiv.org/abs/{urllib.parse.quote(arxiv_id, safe='/')}",
            version="preprint",
        )
    ]


def pmc_candidates(record: Record, *, email: str = "", timeout: int = 30, **_: Any) -> list[Candidate]:
    if not record.pmcid:
        return []
    bucket = "https://pmc-oa-opendata.s3.amazonaws.com/"
    listing_url = bucket + "?" + urllib.parse.urlencode(
        {
            "list-type": "2",
            "prefix": f"{record.pmcid}.",
            "delimiter": "/",
        }
    )
    data, _, _ = request_bytes(listing_url, email=email, timeout=timeout)
    root = ET.fromstring(data)
    ns = "{http://s3.amazonaws.com/doc/2006-03-01/}"
    prefixes = [
        node.text or ""
        for node in root.findall(f".//{ns}CommonPrefixes/{ns}Prefix")
        if node.text and node.text.startswith(f"{record.pmcid}.")
    ]
    prefixes.sort(
        key=lambda value: int(value.rstrip("/").rsplit(".", 1)[-1]),
        reverse=True,
    )
    candidates: list[Candidate] = []
    for prefix in prefixes:
        version_name = prefix.rstrip("/")
        metadata_url = f"{bucket}{prefix}{version_name}.json"
        metadata = request_json(metadata_url, email=email, timeout=timeout)
        if not metadata.get("is_pmc_openaccess"):
            continue
        href = str(metadata.get("pdf_url") or "")
        if href.startswith("s3://pmc-oa-opendata/"):
            href = bucket + href.split("s3://pmc-oa-opendata/", 1)[1]
        if href:
            candidates.append(
                Candidate(
                    "pmc",
                    href,
                    landing_page=f"https://pmc.ncbi.nlm.nih.gov/articles/{record.pmcid}/",
                    license=str(metadata.get("license_code") or ""),
                    version=f"PMC article version {metadata.get('version', '')}".strip(),
                )
            )
    return candidates


def europe_pmc_candidates(
    record: Record,
    *,
    email: str = "",
    timeout: int = 30,
    **_: Any,
) -> list[Candidate]:
    if not record.doi or record.pmcid:
        return []
    query = f'DOI:"{record.doi}" AND OPEN_ACCESS:Y'
    url = "https://www.ebi.ac.uk/europepmc/webservices/rest/search?" + urllib.parse.urlencode(
        {"query": query, "format": "json", "pageSize": 10}
    )
    payload = request_json(url, email=email, timeout=timeout)
    results = payload.get("resultList", {}).get("result", [])
    candidates: list[Candidate] = []
    for result in results:
        if str(result.get("doi", "")).lower() != record.doi:
            continue
        pmcid = str(result.get("pmcid", "")).upper()
        if not pmcid:
            continue
        proxy = Record.from_dict({**record.to_dict(), "pmcid": pmcid})
        candidates.extend(pmc_candidates(proxy, email=email, timeout=timeout))
    return candidates


def unpaywall_candidates(
    record: Record,
    *,
    email: str = "",
    timeout: int = 30,
    **_: Any,
) -> list[Candidate]:
    if not record.doi or not email:
        return []
    url = (
        f"https://api.unpaywall.org/v2/{urllib.parse.quote(record.doi, safe='')}"
        + "?"
        + urllib.parse.urlencode({"email": email})
    )
    payload = request_json(url, email=email, timeout=timeout)
    locations = []
    best = payload.get("best_oa_location")
    if isinstance(best, dict):
        locations.append(best)
    locations.extend(item for item in payload.get("oa_locations", []) if isinstance(item, dict))
    candidates: list[Candidate] = []
    seen: set[str] = set()
    for location in locations:
        pdf_url = str(location.get("url_for_pdf") or "")
        landing = str(location.get("url_for_landing_page") or "")
        target = pdf_url or landing
        if not target or target in seen:
            continue
        seen.add(target)
        candidates.append(
            Candidate(
                "unpaywall",
                target,
                landing_page=landing,
                license=str(location.get("license") or ""),
                version=str(location.get("version") or ""),
                note="landing-page resolution may be required" if not pdf_url else "",
            )
        )
    return candidates


def openalex_candidates(
    record: Record,
    *,
    api_key: str = "",
    email: str = "",
    timeout: int = 30,
    **_: Any,
) -> list[Candidate]:
    if not record.doi or not api_key:
        return []
    identifier = urllib.parse.quote(f"https://doi.org/{record.doi}", safe="")
    url = f"https://api.openalex.org/works/{identifier}?" + urllib.parse.urlencode(
        {"api_key": api_key}
    )
    payload = request_json(url, email=email, timeout=timeout)
    locations = []
    best = payload.get("best_oa_location")
    if isinstance(best, dict):
        locations.append(best)
    locations.extend(item for item in payload.get("locations", []) if isinstance(item, dict))
    candidates: list[Candidate] = []
    seen: set[str] = set()
    for location in locations:
        target = str(location.get("pdf_url") or "")
        landing = str(location.get("landing_page_url") or "")
        if not target or target in seen:
            continue
        seen.add(target)
        candidates.append(
            Candidate(
                "openalex",
                target,
                landing_page=landing,
                license=str(location.get("license") or ""),
                version=str(location.get("version") or ""),
            )
        )
    return candidates


def core_candidates(
    record: Record,
    *,
    api_key: str = "",
    email: str = "",
    timeout: int = 30,
    **_: Any,
) -> list[Candidate]:
    if not record.doi or not api_key:
        return []
    url = "https://api.core.ac.uk/v3/search/works?" + urllib.parse.urlencode(
        {"q": f'doi:"{record.doi}"', "limit": 10}
    )
    payload = request_json(
        url,
        email=email,
        timeout=timeout,
        headers={"Authorization": f"Bearer {api_key}"},
    )
    candidates: list[Candidate] = []
    seen: set[str] = set()
    for item in payload.get("results", []):
        item_doi = str(item.get("doi") or "").lower().removeprefix("https://doi.org/")
        if item_doi and item_doi != record.doi:
            continue
        urls = [item.get("downloadUrl")]
        urls.extend(item.get("sourceFulltextUrls") or [])
        for target in urls:
            target = str(target or "")
            if not target or target in seen:
                continue
            seen.add(target)
            candidates.append(
                Candidate(
                    "core",
                    target,
                    landing_page=str(item.get("fullTextLink") or ""),
                    note="aggregated repository copy",
                )
            )
    return candidates


def doaj_candidates(
    record: Record,
    *,
    email: str = "",
    timeout: int = 30,
    **_: Any,
) -> list[Candidate]:
    if not record.doi:
        return []
    query = urllib.parse.quote(f'bibjson.identifier.id:"{record.doi}"', safe="")
    url = f"https://doaj.org/api/search/articles/{query}?pageSize=10"
    payload = request_json(url, email=email, timeout=timeout)
    candidates: list[Candidate] = []
    seen: set[str] = set()
    for item in payload.get("results", []):
        bibjson = item.get("bibjson", {})
        for link in bibjson.get("link", []):
            target = str(link.get("url") or "")
            if not target or target in seen:
                continue
            seen.add(target)
            candidates.append(
                Candidate(
                    "doaj",
                    target,
                    license=", ".join(
                        str(entry.get("title") or "")
                        for entry in bibjson.get("license", [])
                        if isinstance(entry, dict)
                    ),
                    note="DOAJ full-text or landing-page link",
                )
            )
    return candidates


PROVIDERS = {
    "direct": direct_candidates,
    "arxiv": arxiv_candidates,
    "pmc": pmc_candidates,
    "europe-pmc": europe_pmc_candidates,
    "unpaywall": unpaywall_candidates,
    "openalex": openalex_candidates,
    "core": core_candidates,
    "doaj": doaj_candidates,
}


def discover(
    record: Record,
    provider_names: list[str],
    *,
    email: str = "",
    openalex_api_key: str = "",
    core_api_key: str = "",
    timeout: int = 30,
) -> tuple[list[Candidate], list[dict[str, str]]]:
    candidates: list[Candidate] = []
    errors: list[dict[str, str]] = []
    seen_urls: set[str] = set()
    for name in provider_names:
        provider = PROVIDERS[name]
        try:
            kwargs: dict[str, Any] = {"email": email, "timeout": timeout}
            if name == "openalex":
                kwargs["api_key"] = openalex_api_key
            if name == "core":
                kwargs["api_key"] = core_api_key
            for candidate in provider(record, **kwargs):
                if candidate.url not in seen_urls:
                    candidates.append(candidate)
                    seen_urls.add(candidate.url)
        except (ScholarBridgeError, ET.ParseError, ValueError) as exc:
            errors.append({"provider": name, "error": str(exc)})
    return candidates, errors
