#!/usr/bin/env python3
"""Platform-specific semantics without storing credentials or hidden endpoints."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PlatformAdapter:
    name: str
    home_url: str
    role: str = "full-text"
    preferred_backend: str = "playwright"
    search_input_terms: tuple[str, ...] = ()
    search_input_roles: tuple[str, ...] = (
        "textbox",
        "input",
        "searchbox",
        "combobox",
    )
    search_button_terms: tuple[str, ...] = ("search", "检索", "搜索", "查询")
    result_roles: tuple[str, ...] = ("link", "heading")
    download_terms: tuple[str, ...] = ()
    notes: str = ""


PLATFORM_ADAPTERS: dict[str, PlatformAdapter] = {
    "cnki": PlatformAdapter(
        name="cnki",
        home_url="https://kns.cnki.net/kns8s/defaultresult/index",
        preferred_backend="webbridge",
        search_input_terms=("检索", "主题", "篇名", "关键词"),
        download_terms=("pdf下载", "下载pdf", "pdf全文下载"),
        notes="Certificate, institution route, and page version vary by network.",
    ),
    "wanfang": PlatformAdapter(
        name="wanfang",
        home_url="https://www.wanfangdata.com.cn/index.html",
        search_input_terms=("海量资源", "等你发现", "检索词", "题名"),
        download_terms=("下载全文", "pdf下载", "下载pdf", "全文下载"),
    ),
    "cqvip": PlatformAdapter(
        name="cqvip",
        home_url="https://www.cqvip.com/",
        search_input_terms=("请输入检索词", "检索词", "篇名"),
        download_terms=("pdf下载", "下载pdf", "全文下载", "下载全文"),
    ),
    "science-direct": PlatformAdapter(
        name="science-direct",
        home_url="https://www.sciencedirect.com/",
        search_input_terms=("qs", "keywords", "title", "search"),
        search_button_terms=("submit quick search", "search"),
        download_terms=("download pdf", "view pdf", "pdf"),
    ),
    "springer-nature": PlatformAdapter(
        name="springer-nature",
        home_url="https://link.springer.com/",
        preferred_backend="webbridge",
        search_input_terms=("search", "keyword", "title"),
        download_terms=("download pdf", "pdf"),
        notes="Automated contexts may receive HTTP 406; prefer an existing browser.",
    ),
    "wiley": PlatformAdapter(
        name="wiley",
        home_url="https://onlinelibrary.wiley.com/",
        preferred_backend="webbridge",
        search_input_terms=("search", "title", "keyword"),
        download_terms=("pdf", "download pdf"),
        notes="Cloudflare may require a normal existing browser and human check.",
    ),
    "ieee": PlatformAdapter(
        name="ieee",
        home_url="https://ieeexplore.ieee.org/Xplore/home.jsp",
        search_input_terms=("main", "search"),
        download_terms=("pdf", "download pdf", "open pdf"),
    ),
    "web-of-science": PlatformAdapter(
        name="web-of-science",
        home_url="https://www.webofscience.com/",
        role="licensed-index",
        preferred_backend="webbridge",
        notes="Use for discovery/export; resolve DOI to the actual full-text provider.",
    ),
    "scopus": PlatformAdapter(
        name="scopus",
        home_url="https://www.scopus.com/pages/home",
        role="licensed-index",
        search_input_terms=("search documents", "document search", "search"),
        notes="Use for discovery/export; resolve DOI to the actual full-text provider.",
    ),
    "proquest": PlatformAdapter(
        name="proquest",
        home_url="https://www.proquest.com/",
        preferred_backend="webbridge",
        search_input_terms=("search", "检索"),
        download_terms=("download pdf", "full text pdf", "pdf"),
    ),
    "ebsco": PlatformAdapter(
        name="ebsco",
        home_url="https://search.ebscohost.com/",
        preferred_backend="webbridge",
        search_input_terms=("search", "find"),
        download_terms=("pdf full text", "download pdf", "pdf"),
    ),
}


def get_platform_adapter(name: str) -> PlatformAdapter | None:
    return PLATFORM_ADAPTERS.get(name.strip().casefold())
