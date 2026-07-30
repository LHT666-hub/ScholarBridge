#!/usr/bin/env python3
"""Shared browser-backend contract for authorized literature acquisition."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol


class BrowserBackendError(RuntimeError):
    """Raised when an authorized browser backend cannot complete an action."""


class BrowserBackend(Protocol):
    """Minimum interface used by the bounded authorized-download runner."""

    backend_name: str

    def navigate(
        self,
        url: str,
        *,
        new_tab: bool = True,
        group_title: str = "",
    ) -> dict[str, Any]: ...

    def snapshot(self) -> dict[str, Any]: ...

    def click(self, selector: str) -> dict[str, Any]: ...

    def fill(self, selector: str, value: str) -> dict[str, Any]: ...

    def list_tabs(self) -> dict[str, Any]: ...

    def find_tab(self, url: str) -> dict[str, Any]: ...

    def click_download(
        self,
        selector: str,
        *,
        download_dir: Path,
        timeout: int,
    ) -> Path | None: ...

    def close(self) -> None: ...
