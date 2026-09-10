"""Hosted fetch-and-persist entrypoint with local model work disabled."""

from __future__ import annotations

import argparse
from contextlib import redirect_stdout
import json
import os
from pathlib import Path
import sys
import traceback
from typing import Callable, TextIO

from scraper import harvest


ATS_SOURCES = tuple(harvest.SOURCE_ORDER[1:])
ALL_SOURCES = ("linkedin", *ATS_SOURCES)


class _LastLineTee:
    """Stream stdout while retaining the final non-empty line for parsing."""

    def __init__(self, sink: TextIO) -> None:
        self._sink = sink
        self._pending = ""
        self._last_line = ""

    def write(self, value: str) -> int:
        written = self._sink.write(value)
        self._sink.flush()
        self._pending += value
        while "\n" in self._pending:
            line, self._pending = self._pending.split("\n", 1)
            if line.strip():
                self._last_line = line.strip()
        return written

    def flush(self) -> None:
        self._sink.flush()

    def final_line(self) -> str:
        return self._pending.strip() or self._last_line


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fetch public job sources and persist them without model calls."
    )
    parser.add_argument("--max-pages", type=int, default=1)
    parser.add_argument("--jd-fetch-cap", type=int, default=40)
    parser.add_argument(
        "--recency", choices=("r10800", "r43200", "r604800", "r2592000")
    )
    parser.add_argument(
        "--receipt", type=Path, default=Path("cloud-scrape-receipt.json")
    )
    return parser


def _write_receipt(path: Path, receipt: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _base_receipt(exit_code: int) -> dict[str, object]:
    return {
        "schema_version": 1,
        "run_id": os.environ.get("GITHUB_RUN_ID", "local"),
        "status": "success" if exit_code == 0 else "failure",
        "exit_code": exit_code,
        # LinkedIn is always-on inside harvest; --sources enables only ATS adapters.
        "sources": list(ALL_SOURCES),
    }


def main(
    argv: list[str] | None = None,
    *,
    harvest_main: Callable[[list[str]], int] = harvest.main,
) -> int:
    args = build_argument_parser().parse_args(argv)
    if args.max_pages < 1:
        raise SystemExit("--max-pages must be at least 1")
    if args.jd_fetch_cap < 0:
        raise SystemExit("--jd-fetch-cap must be non-negative")

    if not os.environ.get("DATABASE_URL", "").strip():
        receipt = _base_receipt(2)
        receipt["error_code"] = "MissingDatabaseURL"
        _write_receipt(args.receipt, receipt)
        print(json.dumps(receipt, sort_keys=True))
        return 2

    harvest_args = [
        "--no-annotate",
        "--max-pages",
        str(args.max_pages),
        "--jd-fetch-cap",
        str(args.jd_fetch_cap),
        "--sources",
        ",".join(ATS_SOURCES),
    ]
    if args.recency:
        harvest_args.extend(("--recency", args.recency))

    output = _LastLineTee(sys.stdout)
    try:
        with redirect_stdout(output):
            exit_code = harvest_main(harvest_args)
    except Exception:
        receipt = _base_receipt(1)
        receipt["error_code"] = "HarvesterException"
        _write_receipt(args.receipt, receipt)
        print(json.dumps(receipt, sort_keys=True))
        traceback.print_exc()
        return 1

    receipt = _base_receipt(exit_code)
    if exit_code == 0:
        try:
            result = json.loads(output.final_line())
        except json.JSONDecodeError:
            exit_code = 1
            receipt = _base_receipt(exit_code)
            receipt["error_code"] = "InvalidHarvesterSummary"
        else:
            if isinstance(result, dict):
                receipt["result"] = result
            else:
                exit_code = 1
                receipt = _base_receipt(exit_code)
                receipt["error_code"] = "InvalidHarvesterSummary"
    else:
        receipt["error_code"] = "HarvesterFailed"

    _write_receipt(args.receipt, receipt)
    print(json.dumps(receipt, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
