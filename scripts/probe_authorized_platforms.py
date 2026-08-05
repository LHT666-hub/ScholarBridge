#!/usr/bin/env python3
"""Probe authorized literature platforms without logging in or downloading files."""

from __future__ import annotations

import argparse
import json
import re
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from platform_adapters import PLATFORM_ADAPTERS, PlatformAdapter
from playwright_persistent_client import (
    PlaywrightPersistentClient,
    PlaywrightPersistentError,
)


REF_RE = re.compile(r"(@e[\w-]+)")
AUTH_TERMS = (
    "登录",
    "sign in",
    "log in",
    "institutional access",
    "check access",
    "openathens",
    "shibboleth",
)
BLOCK_TERMS = (
    "just a moment",
    "precondition failed",
    "not acceptable",
    "unable to load page",
    "unusual traffic",
    "captcha",
    "安全验证",
    "异常访问",
)


def _choose_ref(
    tree: str,
    terms: tuple[str, ...],
    roles: tuple[str, ...],
) -> str:
    best_ref, best_score = "", 0
    for line in tree.splitlines():
        match = REF_RE.search(line)
        if not match:
            continue
        lowered = line.casefold()
        if roles and not any(role.casefold() in lowered for role in roles):
            continue
        score = sum(term.casefold() in lowered for term in terms)
        if score > best_score:
            best_ref, best_score = match.group(1), score
    return best_ref


def _contains(text: str, terms: tuple[str, ...]) -> bool:
    lowered = text.casefold()
    return any(term.casefold() in lowered for term in terms)


def _wait_for_page_change(
    client: PlaywrightPersistentClient,
    *,
    before_url: str,
    before_title: str,
    before_tree: str,
    timeout: int = 15,
) -> tuple[dict[str, Any], bool]:
    """Wait for slow SPA/database searches and report whether anything changed."""
    # Several database frontends mutate their home-page DOM immediately after a
    # click, then navigate only seconds later. Do not mistake the first spinner
    # or input-state mutation for a completed search.
    time.sleep(min(8, max(1, timeout)))
    deadline = time.monotonic() + max(0, timeout - 8)
    latest = client.snapshot()
    while time.monotonic() < deadline:
        current_tree = str(latest.get("tree") or "")
        changed = (
            str(latest.get("url") or "") != before_url
            or str(latest.get("title") or "") != before_title
            or current_tree != before_tree
        )
        if changed and (
            str(latest.get("url") or "") != before_url
            or str(latest.get("title") or "") != before_title
        ):
            return latest, True
        time.sleep(1)
        latest = client.snapshot()
    current_tree = str(latest.get("tree") or "")
    return latest, (
        str(latest.get("url") or "") != before_url
        or str(latest.get("title") or "") != before_title
        or current_tree != before_tree
    )


def probe_one(
    adapter: PlatformAdapter,
    *,
    profile_dir: Path,
    download_dir: Path,
    headless: bool,
    timeout: int,
    query: str,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "platform": adapter.name,
        "role": adapter.role,
        "preferred_backend": adapter.preferred_backend,
        "requested_url": adapter.home_url,
        "headless": headless,
        "state": "probe-error",
        "error": "",
    }
    client = None
    try:
        client = PlaywrightPersistentClient(
            profile_dir=profile_dir,
            download_dir=download_dir,
            headless=headless,
            timeout=timeout,
        )
        navigation = client.navigate(adapter.home_url, new_tab=False)
        snapshot = client.snapshot()
        tree = str(snapshot.get("tree") or "")
        status = navigation.get("status")
        search_input = _choose_ref(
            tree,
            adapter.search_input_terms,
            adapter.search_input_roles,
        )
        search_button = _choose_ref(
            tree,
            adapter.search_button_terms,
            ("button", "link"),
        )
        blocked = (
            status in {403, 406, 412, 418, 429}
            or _contains(tree, BLOCK_TERMS)
        )
        row.update(
            {
                "final_url": snapshot.get("url"),
                "title": snapshot.get("title"),
                "http_status": status,
                "navigation_warning": navigation.get("warning", ""),
                "control_count": sum(
                    "@e" in line for line in tree.splitlines()
                ),
                "search_input_found": bool(search_input),
                "search_button_found": bool(search_button),
                "login_visible": _contains(tree, AUTH_TERMS),
                "blocked_or_challenged": blocked,
                "state": "blocked-or-challenged" if blocked else "page-readable",
            }
        )
        if query and search_input and search_button and not blocked:
            client.fill(search_input, query)
            client.click(search_button)
            result, changed = _wait_for_page_change(
                client,
                before_url=str(snapshot.get("url") or ""),
                before_title=str(snapshot.get("title") or ""),
                before_tree=tree,
            )
            row.update(
                {
                    "state": (
                        "search-page-readable"
                        if changed
                        else "search-submission-unconfirmed"
                    ),
                    "search_result_url": result.get("url"),
                    "search_result_title": result.get("title"),
                    "search_result_control_count": sum(
                        "@e" in line
                        for line in str(result.get("tree") or "").splitlines()
                    ),
                }
            )
    except PlaywrightPersistentError as exc:
        message = str(exc)
        row["error"] = message
        row["state"] = (
            "tls-or-network-error"
            if "CERT_" in message or "certificate" in message.casefold()
            else "probe-error"
        )
    finally:
        if client:
            client.close()
    return row


def write_report(output_dir: Path, rows: list[dict[str, Any]]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "records": rows,
    }
    (output_dir / "platform-probe.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    lines = [
        "# Authorized platform probe",
        "",
        "This report tests page access and visible search controls only. It does not",
        "prove subscription access or PDF download success.",
        "",
        "| Platform | Role | State | HTTP | Search controls | Preferred backend |",
        "|---|---|---|---:|---|---|",
    ]
    for row in rows:
        controls = (
            "yes"
            if row.get("search_input_found") and row.get("search_button_found")
            else "no"
        )
        lines.append(
            f"| {row['platform']} | {row['role']} | {row['state']} | "
            f"{row.get('http_status', '')} | {controls} | "
            f"{row['preferred_backend']} |"
        )
    lines.extend(
        [
            "",
            "A page-readable result is not a completed database route. The next level",
            "requires user authentication, a native PDF control, a validated download,",
            "and successful Zotero attachment.",
        ]
    )
    (output_dir / "platform-probe.md").write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--platform",
        action="append",
        choices=sorted(PLATFORM_ADAPTERS),
        help="Repeat for multiple platforms; omit to probe all configured platforms.",
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--profile-root", type=Path)
    parser.add_argument("--download-dir", type=Path)
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--timeout", type=int, default=35)
    parser.add_argument(
        "--query",
        default="",
        help="Optional single search query. The probe never opens or downloads a result.",
    )
    args = parser.parse_args()
    names = args.platform or sorted(PLATFORM_ADAPTERS)
    temporary = None
    if args.profile_root:
        profile_root = args.profile_root.expanduser().resolve()
        profile_root.mkdir(parents=True, exist_ok=True)
    else:
        temporary = tempfile.TemporaryDirectory()
        profile_root = Path(temporary.name)
    download_dir = (
        args.download_dir.expanduser().resolve()
        if args.download_dir
        else args.output_dir / "downloads"
    )
    rows = [
        probe_one(
            PLATFORM_ADAPTERS[name],
            profile_dir=profile_root / name,
            download_dir=download_dir,
            headless=args.headless,
            timeout=args.timeout,
            query=args.query,
        )
        for name in names
    ]
    write_report(args.output_dir, rows)
    if temporary:
        temporary.cleanup()
    print(json.dumps({"records": len(rows), "output": str(args.output_dir)}, ensure_ascii=False))
    return 2 if any(row["state"] == "probe-error" for row in rows) else 0


if __name__ == "__main__":
    raise SystemExit(main())
