#!/usr/bin/env python3
"""Execute bounded authorized downloads through a selected browser backend."""

from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path
from typing import Any

from browser_backend import BrowserBackend, BrowserBackendError
from common import read_jsonl, write_jsonl
from playwright_persistent_client import PlaywrightPersistentClient
from platform_adapters import PlatformAdapter, get_platform_adapter
from webbridge_client import (
    WebBridgeClient,
    daemon_ready,
    start_local_daemon,
)


REF_RE = re.compile(r"(@e[\w-]+)")
PARTIAL_SUFFIXES = {".crdownload", ".part", ".download", ".tmp"}
DOWNLOAD_TERMS = (
    "pdf下载",
    "下载pdf",
    "全文下载",
    "download pdf",
    "full text pdf",
    "pdf",
)
SEARCH_INPUT_TERMS = ("检索", "搜索", "主题", "篇名", "题名", "search", "title")
SEARCH_BUTTON_TERMS = ("检索", "搜索", "查询", "search")
WARNING_TERMS = (
    "访问过于频繁",
    "异常访问",
    "安全验证",
    "账号异常",
    "ip异常",
    "too many requests",
    "unusual traffic",
    "captcha",
)
AUTH_TERMS = (
    "机构登录",
    "账号登录",
    "登录后下载",
    "请登录",
    "sign in",
    "log in",
)
EXCLUDE_DOWNLOAD_TERMS = ("caj", "参考文献", "引文", "客户端下载", "app")


def _tree(snapshot: dict[str, Any]) -> str:
    value = snapshot.get("tree", "")
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def _line_refs(tree: str) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    for line in tree.splitlines():
        match = REF_RE.search(line)
        if match:
            rows.append((match.group(1), line.strip()))
    return rows


def _choose_ref(
    tree: str,
    terms: tuple[str, ...],
    *,
    excludes: tuple[str, ...] = (),
    role_terms: tuple[str, ...] = (),
) -> str:
    best = ("", -1)
    for ref, line in _line_refs(tree):
        lowered = line.casefold()
        if any(term.casefold() in lowered for term in excludes):
            continue
        if role_terms and not any(term.casefold() in lowered for term in role_terms):
            continue
        score = sum(3 if lowered.strip().startswith(term.casefold()) else 1 for term in terms if term.casefold() in lowered)
        if score > best[1]:
            best = (ref, score)
    return best[0] if best[1] > 0 else ""


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    lowered = text.casefold()
    return any(term.casefold() in lowered for term in terms)


def _download_state(root: Path) -> dict[Path, tuple[int, int]]:
    state = {}
    if not root.exists():
        return state
    for path in root.rglob("*"):
        if path.is_file():
            stat = path.stat()
            state[path.resolve()] = (stat.st_size, stat.st_mtime_ns)
    return state


def _wait_for_pdf(
    root: Path,
    before: dict[Path, tuple[int, int]],
    *,
    timeout: int,
    interval: float = 0.5,
) -> Path | None:
    deadline = time.monotonic() + timeout
    last: tuple[Path, int] | None = None
    stable = 0
    while time.monotonic() < deadline:
        partial = any(
            path.is_file() and path.suffix.casefold() in PARTIAL_SUFFIXES
            for path in root.rglob("*")
        )
        candidates = []
        for path in root.rglob("*.pdf"):
            resolved = path.resolve()
            stat = path.stat()
            old = before.get(resolved)
            if old is None or old != (stat.st_size, stat.st_mtime_ns):
                candidates.append((stat.st_mtime_ns, path, stat.st_size))
        if candidates and not partial:
            _, newest, size = max(candidates)
            current = (newest.resolve(), size)
            if current == last:
                stable += 1
            else:
                last = current
                stable = 0
            if stable >= 1 and size > 0:
                return newest
        time.sleep(interval)
    return None


def _select_new_tab(
    client: BrowserBackend,
    before_urls: set[str],
) -> None:
    try:
        response = client.list_tabs()
    except BrowserBackendError:
        return
    tabs = response.get("tabs", [])
    if not isinstance(tabs, list):
        return
    for tab in reversed(tabs):
        if not isinstance(tab, dict):
            continue
        url = str(tab.get("url") or "")
        if url and url not in before_urls:
            try:
                client.find_tab(url)
            except BrowserBackendError:
                pass
            return


def _wait_for_page_change(
    client: BrowserBackend,
    before_tree: str,
    *,
    settle_seconds: float,
    max_wait: float = 15.0,
) -> str:
    """Allow slow database SPAs to finish without a fixed long sleep."""
    # Database SPAs often update a spinner immediately but need several seconds
    # before result links exist. Give them a bounded minimum settling window.
    time.sleep(max(6.0, settle_seconds))
    deadline = time.monotonic() + max(0.0, max_wait - max(6.0, settle_seconds))
    latest = _tree(client.snapshot())
    while time.monotonic() < deadline:
        time.sleep(max(0.25, min(1.0, settle_seconds)))
        latest = _tree(client.snapshot())
        if latest != before_tree:
            return latest
    return latest


def _search_to_article(
    client: BrowserBackend,
    tree: str,
    title: str,
    *,
    adapter: PlatformAdapter | None,
    settle_seconds: float,
) -> tuple[str, str]:
    input_terms = (
        (adapter.search_input_terms + SEARCH_INPUT_TERMS)
        if adapter
        else SEARCH_INPUT_TERMS
    )
    input_roles = adapter.search_input_roles if adapter else (
        "textbox",
        "input",
        "searchbox",
        "combobox",
    )
    input_ref = _choose_ref(
        tree,
        input_terms,
        role_terms=input_roles,
    )
    if not input_ref:
        return tree, "search-input-not-found"
    client.fill(input_ref, title)
    button_terms = (
        adapter.search_button_terms if adapter else SEARCH_BUTTON_TERMS
    )
    button_ref = _choose_ref(
        tree,
        button_terms,
        role_terms=("button", "link"),
    )
    if not button_ref:
        return tree, "search-button-not-found"
    client.click(button_ref)
    results = _wait_for_page_change(
        client,
        tree,
        settle_seconds=settle_seconds,
    )
    title_terms = tuple(
        part for part in re.split(r"[\s:：，,。.!！?？()（）\[\]]+", title.casefold()) if len(part) >= 3
    )
    result_ref = _choose_ref(
        results,
        title_terms[:5] or (title,),
        role_terms=("link", "heading"),
    )
    if not result_ref:
        return results, "result-link-not-found"
    before_tabs = client.list_tabs().get("tabs", [])
    before_urls = {
        str(tab.get("url") or "")
        for tab in before_tabs
        if isinstance(tab, dict)
    }
    client.click(result_ref)
    time.sleep(settle_seconds)
    _select_new_tab(client, before_urls)
    return _tree(client.snapshot()), ""


def execute_row(
    row: dict[str, Any],
    *,
    client: BrowserBackend,
    download_dir: Path,
    download_timeout: int,
    settle_seconds: float,
    first_navigation: bool,
) -> dict[str, Any]:
    updated = dict(row)
    platform = str(row.get("platform") or "")
    adapter = get_platform_adapter(platform)
    if adapter and adapter.role == "licensed-index":
        updated["state"] = "discovery-export-only"
        updated["browser_error"] = (
            "This platform is a licensed discovery index, not the final PDF "
            "host. Export DOI/metadata and route it to the publisher or OA resolver."
        )
        return updated
    url = str(row.get("start_url") or "")
    if not url:
        updated["state"] = "needs-identifier-or-url"
        updated["browser_error"] = "no start_url"
        return updated
    try:
        client.navigate(
            url,
            new_tab=True,
            group_title="ScholarBridge 授权文献下载" if first_navigation else "",
        )
        time.sleep(settle_seconds)
        tree = _tree(client.snapshot())
        if _contains_any(tree, WARNING_TERMS):
            updated["state"] = "stopped-platform-warning"
            updated["browser_error"] = "platform warning or CAPTCHA detected"
            return updated

        download_terms = (
            (adapter.download_terms + DOWNLOAD_TERMS)
            if adapter
            else DOWNLOAD_TERMS
        )
        download_ref = _choose_ref(
            tree,
            download_terms,
            excludes=EXCLUDE_DOWNLOAD_TERMS,
            role_terms=("link", "button"),
        )
        if not download_ref and row.get("title"):
            tree, search_error = _search_to_article(
                client,
                tree,
                str(row["title"]),
                adapter=adapter,
                settle_seconds=settle_seconds,
            )
            if search_error:
                updated["state"] = (
                    "needs-user-authentication"
                    if _contains_any(tree, AUTH_TERMS)
                    else "needs-manual-browser-step"
                )
                updated["browser_error"] = search_error
                updated["snapshot_excerpt"] = tree[:1500]
                return updated
            if _contains_any(tree, WARNING_TERMS):
                updated["state"] = "stopped-platform-warning"
                updated["browser_error"] = "platform warning or CAPTCHA detected"
                return updated
            download_ref = _choose_ref(
                tree,
                download_terms,
                excludes=EXCLUDE_DOWNLOAD_TERMS,
                role_terms=("link", "button"),
            )

        if not download_ref:
            updated["state"] = (
                "needs-user-authentication"
                if _contains_any(tree, AUTH_TERMS)
                else "download-control-not-found"
            )
            updated["browser_error"] = "no visible native PDF download control"
            updated["snapshot_excerpt"] = tree[:1500]
            return updated

        before = _download_state(download_dir)
        downloaded = client.click_download(
            download_ref,
            download_dir=download_dir,
            timeout=download_timeout,
        )
        if downloaded is None:
            downloaded = _wait_for_pdf(
                download_dir,
                before,
                timeout=download_timeout,
            )
        if downloaded is None:
            updated["state"] = "download-clicked-no-file"
            updated["browser_error"] = (
                "download control was clicked but no completed PDF appeared; "
                "check browser prompts or platform format"
            )
            return updated
        updated["state"] = "browser-download-complete"
        updated["downloaded_filename"] = downloaded.name
        updated["browser_error"] = ""
        return updated
    except BrowserBackendError as exc:
        updated["state"] = "browser-error"
        updated["browser_error"] = str(exc)
        return updated


def run(
    queue_path: Path,
    download_dir: Path,
    output_dir: Path,
    *,
    execute: bool,
    backend: str,
    base_url: str,
    session: str,
    profile_dir: Path,
    chrome_executable: Path | None,
    headless: bool,
    max_records: int,
    download_timeout: int,
    settle_seconds: float,
    start_daemon: bool,
) -> dict[str, Any]:
    rows = read_jsonl(queue_path)
    if max_records > 0:
        selected = rows[:max_records]
        remainder = rows[max_records:]
    else:
        selected, remainder = rows, []
    output_dir.mkdir(parents=True, exist_ok=True)
    download_dir.mkdir(parents=True, exist_ok=True)

    if not execute:
        updated = [
            {**row, "state": "browser-dry-run", "browser_error": ""}
            for row in selected
        ] + remainder
    else:
        if backend == "webbridge":
            if base_url == "http://127.0.0.1:10086" and not daemon_ready():
                if not start_daemon or not start_local_daemon():
                    raise BrowserBackendError(
                        "Kimi WebBridge daemon is not reachable on "
                        "127.0.0.1:10086"
                    )
                for _ in range(20):
                    if daemon_ready():
                        break
                    time.sleep(0.25)
            client: BrowserBackend = WebBridgeClient(
                base_url=base_url,
                session=session,
            )
        elif backend == "playwright":
            client = PlaywrightPersistentClient(
                profile_dir=profile_dir,
                download_dir=download_dir,
                chrome_executable=chrome_executable,
                headless=headless,
                timeout=max(download_timeout, 30),
            )
        else:
            raise BrowserBackendError(f"unsupported browser backend: {backend}")

        updated = []
        try:
            for index, row in enumerate(selected):
                result = execute_row(
                    row,
                    client=client,
                    download_dir=download_dir,
                    download_timeout=download_timeout,
                    settle_seconds=settle_seconds,
                    first_navigation=index == 0,
                )
                result["browser_backend"] = backend
                updated.append(result)
                if result["state"] == "stopped-platform-warning":
                    updated.extend(selected[index + 1 :])
                    break
            updated.extend(remainder)
        finally:
            client.close()

    output = output_dir / "authorized-queue.browser.jsonl"
    write_jsonl(output, updated)
    counts: dict[str, int] = {}
    for row in updated:
        state = str(row.get("state") or "unknown")
        counts[state] = counts.get(state, 0) + 1
    summary = {
        "records": len(updated),
        "execute": execute,
        "backend": backend,
        "states": counts,
        "output": str(output),
        "session": session,
    }
    (output_dir / "browser-summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("queue", type=Path)
    parser.add_argument("--download-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument(
        "--backend",
        choices=("webbridge", "playwright"),
        default="webbridge",
        help=(
            "webbridge reuses an already logged-in Chrome; playwright uses a "
            "dedicated persistent profile prepared by prepare_browser_profile.py"
        ),
    )
    parser.add_argument("--webbridge-url", default="http://127.0.0.1:10086")
    parser.add_argument("--session", default="scholarbridge-authorized")
    parser.add_argument(
        "--profile-dir",
        type=Path,
        default=Path.home()
        / ".scholarbridge"
        / "browser-profiles"
        / "authorized-default",
    )
    parser.add_argument("--chrome-executable", type=Path)
    parser.add_argument(
        "--headless",
        action="store_true",
        help=(
            "Run Playwright without a visible window. Intended for local tests; "
            "authorized database workflows should remain visible."
        ),
    )
    parser.add_argument("--max-records", type=int, default=10)
    parser.add_argument("--download-timeout", type=int, default=60)
    parser.add_argument("--settle-seconds", type=float, default=1.5)
    parser.add_argument(
        "--no-start-daemon",
        action="store_true",
        help="Do not start the installed local daemon when port 10086 is closed.",
    )
    args = parser.parse_args()
    summary = run(
        args.queue,
        args.download_dir,
        args.output_dir,
        execute=args.execute,
        backend=args.backend,
        base_url=args.webbridge_url,
        session=args.session,
        profile_dir=args.profile_dir,
        chrome_executable=args.chrome_executable,
        headless=args.headless,
        max_records=args.max_records,
        download_timeout=args.download_timeout,
        settle_seconds=args.settle_seconds,
        start_daemon=not args.no_start_daemon,
    )
    print(json.dumps(summary, ensure_ascii=False))
    warning_states = {"browser-error", "stopped-platform-warning"}
    return 2 if warning_states.intersection(summary["states"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
