"""Decide whether a weekly cache update merits a reviewable data PR."""

import json
from pathlib import Path
import subprocess

CACHE_PATH = Path("scraper/ats-probe-cache.json")


def meaningful_cache_change(previous: dict, current: dict) -> bool:
    """New non-error keys/results or newer miss cooldowns justify a PR.

    Hit/error dates, slug changes, removals, and errors alone do not. The registry has
    its own diff gate, so newly discovered tenants are always eligible.
    """
    return any(
        row["result"] != "error"
        and (
            key not in previous
            or row["result"] != previous[key]["result"]
            or (row["result"] == "miss" and row.get("last_checked_at", "") > previous[key].get("last_checked_at", ""))
        )
        for key, row in current.items()
    )


def main() -> None:
    previous = json.loads(
        subprocess.check_output(["git", "show", f"HEAD:{CACHE_PATH}"], text=True)
    )
    current = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    print("true" if meaningful_cache_change(previous, current) else "false")


if __name__ == "__main__":
    main()
