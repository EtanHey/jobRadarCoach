#!/usr/bin/env python3
"""Reject repository paths that can expose local or credential data."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys


def _git_paths(all_tracked: bool) -> list[bytes]:
    command = (
        ["git", "ls-files", "--full-name", "-z", "--", ":/"]
        if all_tracked
        else [
            "git",
            "diff",
            "--no-relative",
            "--cached",
            "--name-only",
            "--diff-filter=ACMRT",
            "-z",
        ]
    )
    try:
        result = subprocess.run(command, check=False, capture_output=True)
    except OSError:
        print("Private-file guard: Git command failed.", file=sys.stderr)
        raise SystemExit(2) from None
    if result.returncode != 0:
        print("Private-file guard: Git command failed.", file=sys.stderr)
        raise SystemExit(2)
    if not result.stdout:
        return []
    if not result.stdout.endswith(b"\0"):
        print("Private-file guard: Git returned malformed path data.", file=sys.stderr)
        raise SystemExit(2)
    return result.stdout[:-1].split(b"\0")


def _is_private(path: bytes) -> bool:
    components = path.split(b"/")
    name = components[-1]
    is_env_template = name.startswith(b".env.") and name.endswith(
        (b".example", b".sample", b".template")
    )
    return (
        name in {b"profile.yaml", b"auth.json"}
        or b"docs.local" in components
        or (name.startswith(b"credentials") and name.endswith(b".json"))
        or name == b".env"
        or (name.startswith(b".env.") and not is_env_template)
        or (b".local." in name and not is_env_template)
        or any(
            component
            in {
                b"data",
                b".run-state",
                b".run-logs",
                b"logs",
                b"backups",
                b".autocursor-runs",
            }
            for component in components
        )
    )


def _display(path: bytes) -> str:
    decoded = path.decode("utf-8", errors="surrogateescape")
    return json.dumps(decoded, ensure_ascii=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--all-tracked",
        action="store_true",
        help="scan every tracked path instead of only staged changes",
    )
    args = parser.parse_args()
    blocked = [path for path in _git_paths(args.all_tracked) if _is_private(path)]
    if not blocked:
        return 0

    print("Private-file guard rejected these repository paths:", file=sys.stderr)
    for path in blocked:
        print(f"  - {_display(path)}", file=sys.stderr)
    print("Remove them from tracking before continuing.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
