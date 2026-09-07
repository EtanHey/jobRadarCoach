#!/usr/bin/env python3
"""Reproduce a saved Job Radar score boundary from committed JD text."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import harvest


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--profile", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_argument_parser().parse_args(argv)
    rows = json.loads(args.fixture.read_text(encoding="utf-8"))
    if not isinstance(rows, list) or not rows:
        raise ValueError("rescore fixture must be a non-empty list")
    profile = harvest.load_profile_contract(args.profile)
    fit_terms = profile["fit_terms"]
    assert isinstance(fit_terms, set)

    before: list[dict[str, object]] = []
    after: list[dict[str, object]] = []
    mismatches: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("every rescore fixture row must be an object")
        baseline = {**row, "score": int(row["before_score"]), "negative_hits": []}
        rescored = {**row, **harvest.score_posting(row, fit_terms)}
        before.append(baseline)
        after.append(rescored)
        expected_score = int(row["expected_score"])
        expected_hits = list(row["expected_negative_hits"])
        if rescored["score"] != expected_score or rescored["negative_hits"] != expected_hits:
            mismatches.append(
                f"{row['id']}: expected {expected_score}/{expected_hits}, "
                f"got {rescored['score']}/{rescored['negative_hits']}"
            )

    print(harvest.format_rescore_table(before, after))
    if mismatches:
        print("\n".join(mismatches))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
