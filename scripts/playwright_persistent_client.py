#!/usr/bin/env python3
"""Visible Playwright backend with a dedicated persistent browser profile."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from browser_backend import BrowserBackendError


INTERACTIVE_SELECTOR = (
    "a,button,input,textarea,select,"
    "[role=button],[role=link],[role=textbox],[role=searchbox],"
    "[role=option],[role=tab],[contenteditable=true]"
)
REF_RE = re.compile(r"^@e[\w-]+$")


class PlaywrightPersistentError(BrowserBackendError):
    """Raised when the persistent Playwright browser cannot complete an action."""


def _default_chrome() -> Path | None:
    candidates = (
        Path(os.environ.get("PROGRAMFILES", "C:/Program Files"))
        / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("PROGRAMFILES(X86)", "C:/Program Files (x86)"))
        / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("LOCALAPPDATA", ""))
        / "Google/Chrome/Application/chrome.exe",
    )
    return next((path for path in candidates if path.is_file()), None)


def playwright_available() -> bool:
    try:
        import playwright.sync_api  # noqa: F401
    except ImportError:
        return False
    return True


class PlaywrightPersistentClient:
    """Browser adapter that stores login state in a dedicated user-data directory."""

    backend_name = "playwright"

    def __init__(
        self,
        *,
        profile_dir: Path,
        download_dir: Path,
        chrome_executable: Path | None = None,
        headless: bool = False,
        timeout: int = 30,
    ) -> None:
        if not playwright_available():
            raise PlaywrightPersistentError(
                "Python Playwright is not installed. Run "
                "`python -m pip install playwright`, then retry. ScholarBridge "
                "uses the installed Chrome executable, so `playwright install` "
                "is normally unnecessary."
            )
        from playwright.sync_api import sync_playwright

        profile_dir = profile_dir.expanduser().resolve()
        download_dir = download_dir.expanduser().resolve()
        profile_dir.mkdir(parents=True, exist_ok=True)
        download_dir.mkdir(parents=True, exist_ok=True)
        executable = (
            chrome_executable.expanduser().resolve()
            if chrome_executable
            else _default_chrome()
        )
        if executable is None or not executable.is_file():
            raise PlaywrightPersistentError(
                "Google Chrome was not found. Pass --chrome-executable with the "
                "path to chrome.exe."
            )

        self.timeout_ms = max(1, timeout) * 1000
        self._playwright = sync_playwright().start()
        try:
            self._context = self._playwright.chromium.launch_persistent_context(
                user_data_dir=str(profile_dir),
                executable_path=str(executable),
                headless=headless,
                accept_downloads=True,
                downloads_path=str(download_dir),
                viewport=None,
                args=["--start-maximized"],
            )
        except Exception as exc:
            self._playwright.stop()
            raise PlaywrightPersistentError(
                "Could not open the persistent Chrome profile. Close any other "
                "ScholarBridge browser using the same profile and retry: "
                f"{exc}"
            ) from exc
        self._page = (
            self._context.pages[0]
            if self._context.pages
            else self._context.new_page()
        )
        self._page.set_default_timeout(self.timeout_ms)

    def _active_page(self):
        if self._page.is_closed():
            pages = [page for page in self._context.pages if not page.is_closed()]
            if not pages:
                self._page = self._context.new_page()
            else:
                self._page = pages[-1]
        return self._page

    def navigate(
        self,
        url: str,
        *,
        new_tab: bool = True,
        group_title: str = "",
    ) -> dict[str, Any]:
        del group_title
        try:
            if new_tab and self._active_page().url not in ("", "about:blank"):
                self._page = self._context.new_page()
            page = self._active_page()
            response = page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=self.timeout_ms,
            )
            page.bring_to_front()
            return {
                "url": page.url,
                "status": response.status if response else None,
            }
        except Exception as exc:
            raise PlaywrightPersistentError(f"navigate failed: {exc}") from exc

    def snapshot(self) -> dict[str, Any]:
        page = self._active_page()
        try:
            rows = page.locator(INTERACTIVE_SELECTOR).evaluate_all(
                """
                (elements) => {
                  const visible = (el) => {
                    const style = window.getComputedStyle(el);
                    const rect = el.getBoundingClientRect();
                    return style.visibility !== "hidden" &&
                      style.display !== "none" &&
                      rect.width > 0 && rect.height > 0;
                  };
                  return elements.filter(visible).slice(0, 500).map((el, i) => {
                    const ref = `@e${i}`;
                    el.setAttribute("data-scholarbridge-ref", ref);
                    const explicitRole = el.getAttribute("role");
                    const tag = el.tagName.toLowerCase();
                    let role = explicitRole || tag;
                    if (!explicitRole && tag === "a") role = "link";
                    if (!explicitRole && tag === "button") role = "button";
                    if (!explicitRole && ["input", "textarea"].includes(tag)) {
                      role = (el.type === "search") ? "searchbox" : "textbox";
                    }
                    const name = (
                      el.getAttribute("aria-label") ||
                      el.getAttribute("title") ||
                      el.getAttribute("placeholder") ||
                      el.innerText ||
                      el.value ||
                      el.name ||
                      ""
                    ).replace(/\\s+/g, " ").trim().slice(0, 240);
                    return {ref, role, name};
                  });
                }
                """
            )
            tree = "\n".join(
                f'{row.get("role", "element")} "{row.get("name", "")}" '
                f'{row.get("ref", "")}'
                for row in rows
            )
            body_text = page.locator("body").inner_text(timeout=self.timeout_ms)
            return {
                "tree": tree + "\n\nPAGE TEXT\n" + body_text[:12000],
                "url": page.url,
                "title": page.title(),
            }
        except Exception as exc:
            raise PlaywrightPersistentError(f"snapshot failed: {exc}") from exc

    def _locator(self, ref: str):
        if not REF_RE.match(ref):
            raise PlaywrightPersistentError(f"invalid semantic reference: {ref!r}")
        locator = self._active_page().locator(
            f'[data-scholarbridge-ref="{ref}"]'
        )
        if locator.count() < 1:
            raise PlaywrightPersistentError(
                f"semantic reference {ref!r} is stale; take a new snapshot"
            )
        return locator.first

    def click(self, selector: str) -> dict[str, Any]:
        try:
            self._locator(selector).click(timeout=self.timeout_ms)
            return {"clicked": selector}
        except PlaywrightPersistentError:
            raise
        except Exception as exc:
            raise PlaywrightPersistentError(f"click failed: {exc}") from exc

    def fill(self, selector: str, value: str) -> dict[str, Any]:
        try:
            self._locator(selector).fill(value, timeout=self.timeout_ms)
            return {"filled": selector}
        except PlaywrightPersistentError:
            raise
        except Exception as exc:
            raise PlaywrightPersistentError(f"fill failed: {exc}") from exc

    def list_tabs(self) -> dict[str, Any]:
        tabs = []
        for page in self._context.pages:
            if page.is_closed():
                continue
            try:
                title = page.title()
            except Exception:
                title = ""
            tabs.append({"url": page.url, "title": title})
        return {"tabs": tabs}

    def find_tab(self, url: str) -> dict[str, Any]:
        for page in reversed(self._context.pages):
            if not page.is_closed() and page.url == url:
                self._page = page
                page.bring_to_front()
                return {"url": url}
        raise PlaywrightPersistentError(f"tab not found: {url}")

    def click_download(
        self,
        selector: str,
        *,
        download_dir: Path,
        timeout: int,
    ) -> Path | None:
        try:
            page = self._active_page()
            with page.expect_download(timeout=max(1, timeout) * 1000) as pending:
                self._locator(selector).click(timeout=self.timeout_ms)
            download = pending.value
            name = Path(download.suggested_filename).name or "download.pdf"
            target = download_dir / name
            if target.exists():
                stem, suffix = target.stem, target.suffix
                index = 2
                while target.exists():
                    target = download_dir / f"{stem}-{index}{suffix}"
                    index += 1
            download.save_as(str(target))
            return target
        except PlaywrightPersistentError:
            raise
        except Exception as exc:
            # A link may open a PDF viewer rather than emit a browser download.
            # Return None so the caller can report a bounded manual fallback.
            if "Timeout" in type(exc).__name__ or "Timeout" in str(exc):
                return None
            raise PlaywrightPersistentError(
                f"download click failed: {exc}"
            ) from exc

    def close(self) -> None:
        try:
            self._context.close()
        finally:
            self._playwright.stop()
