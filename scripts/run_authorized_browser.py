#!/usr/bin/env python3
"""Execute bounded authorized-download tasks through Kimi WebBridge."""

from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path
from typing import Any

from common import read_jsonl, write_jsonl
from webbridge_client import (
    WebBridgeClient,
    WebBridgeError,
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
    client: WebBridgeClient,
    before_urls: set[str],
) -> None:
    try:
        response = client.list_tabs()
    except WebBridgeError:
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
            except WebBridgeError:
                pass
            return


def _search_to_article(
    client: WebBridgeClient,
    tree: str,
    title: str,
    *,
    settle_seconds: float,
) -> tuple[str, str]:
    input_ref = _choose_ref(
        tree,
        SEARCH_INPUT_TERMS,
        role_terms=("textbox", "input", "searchbox"),
    )
    if not input_ref:
        return tree, "search-input-not-found"
    client.fill(input_ref, title)
    button_ref = _choose_ref(
        tree,
        SEARCH_BUTTON_TERMS,
        role_terms=("button", "link"),
    )
    if not button_ref:
        return tree, "search-button-not-found"
    client.click(button_ref)
    time.sleep(settle_seconds)
    results = _tree(client.snapshot())
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
    client: WebBridgeClient,
    download_dir: Path,
    download_timeout: int,
    settle_seconds: float,
    first_navigation: bool,
) -> dict[str, Any]:
    updated = dict(row)
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

        download_ref = _choose_ref(
            tree,
            DOWNLOAD_TERMS,
            excludes=EXCLUDE_DOWNLOAD_TERMS,
            role_terms=("link", "button"),
        )
        if not download_ref and row.get("title"):
            tree, search_error = _search_to_article(
                client,
                tree,
                str(row["title"]),
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
                DOWNLOAD_TERMS,
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
        client.click(download_ref)
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
    except WebBridgeError as exc:
        updated["state"] = "browser-error"
        updated["browser_error"] = str(exc)
        return updated


def run(
    queue_path: Path,
    download_dir: Path,
    output_dir: Path,
    *,
    execute: bool,
    base_url: str,
    session: str,
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
        if base_url == "http://127.0.0.1:10086" and not daemon_ready():
            if not start_daemon or not start_local_daemon():
                raise WebBridgeError(
                    "Kimi WebBridge daemon is not reachable on 127.0.0.1:10086"
                )
            for _ in range(20):
                if daemon_ready():
                    break
                time.sleep(0.25)
        client = WebBridgeClient(base_url=base_url, session=session)
        updated = []
        for index, row in enumerate(selected):
            result = execute_row(
                row,
                client=client,
                download_dir=download_dir,
                download_timeout=download_timeout,
                settle_seconds=settle_seconds,
                first_navigation=index == 0,
            )
            updated.append(result)
            if result["state"] == "stopped-platform-warning":
                updated.extend(selected[index + 1 :])
                break
        updated.extend(remainder)

    output = output_dir / "authorized-queue.browser.jsonl"
    write_jsonl(output, updated)
    counts: dict[str, int] = {}
    for row in updated:
        state = str(row.get("state") or "unknown")
        counts[state] = counts.get(state, 0) + 1
    summary = {
        "records": len(updated),
        "execute": execute,
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
    parser.add_argument("--webbridge-url", default="http://127.0.0.1:10086")
    parser.add_argument("--session", default="scholarbridge-authorized")
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
        base_url=args.webbridge_url,
        session=args.session,
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

