#!/usr/bin/env python3
"""Open a visible persistent Chrome profile for user-controlled database login."""

from __future__ import annotations

import argparse
from pathlib import Path

from playwright_persistent_client import (
    PlaywrightPersistentClient,
    PlaywrightPersistentError,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile-dir", type=Path, required=True)
    parser.add_argument("--url", required=True)
    parser.add_argument(
        "--download-dir",
        type=Path,
        default=Path.home() / "Downloads",
    )
    parser.add_argument("--chrome-executable", type=Path)
    args = parser.parse_args()

    try:
        client = PlaywrightPersistentClient(
            profile_dir=args.profile_dir,
            download_dir=args.download_dir,
            chrome_executable=args.chrome_executable,
        )
        client.navigate(args.url, new_tab=False)
        print(
            "A dedicated visible Chrome window is open.\n"
            "Complete the database/CARSI/WebVPN login yourself. ScholarBridge "
            "does not read your password or export cookies.\n"
            "After the target database page works normally, return here and "
            "press Enter to save and close this profile."
        )
        input()
        client.close()
    except (PlaywrightPersistentError, KeyboardInterrupt) as exc:
        print(f"Profile preparation stopped: {exc}")
        return 2
    print(f"Persistent login profile saved at: {args.profile_dir.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
