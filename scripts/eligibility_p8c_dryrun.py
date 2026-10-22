"""Offline frozen-snapshot replay; never reads a database or contacts a provider."""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import types

from scraper.eligibility import decide_location_eligibility


BASE = "39a8617"
PROFILE = {"candidate.open_to.geographies": ["Central Israel", "Remote"]}
FIGMA_BULLET_MOVES = {
    "3bb98bc9-a402-4adf-9eb7-53054dd6dbf1",
    "a8471d24-70fa-4775-98c9-cde1f62bfa14",
    "b026a1ce-cbdc-456f-9a8c-c684ef131d38",
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path)
    args = parser.parse_args()
    data = args.snapshot.read_bytes()
    assert hashlib.sha256(data).hexdigest() == (
        "520151e36a5a639705a4e56f727ab6ea522ea57bf4490c92a2f4ac8f11a94297"
    )
    baseline = types.ModuleType("p8c_baseline")
    sys.modules[baseline.__name__] = baseline
    exec(
        subprocess.check_output(
            ["git", "show", f"{BASE}:scraper/eligibility.py"], text=True
        ),
        baseline.__dict__,
    )
    before_counts, after_counts = Counter(), Counter()
    moves, reason_changes = [], []
    issue11 = None
    rows = [json.loads(line) for line in data.decode().split("\n") if line]
    for row in rows:
        extraction = row.get("posting_extractions")
        before = baseline.decide_location_eligibility(row, extraction, PROFILE)
        after = decide_location_eligibility(row, extraction, PROFILE)
        before_counts[before["eligibility"]] += 1
        after_counts[after["eligibility"]] += 1
        change = {
            key: row[key] for key in ("id", "company", "title", "location")
        } | {"before": before, "after": after}
        if before["eligibility"] != after["eligibility"]:
            assert row["id"] in FIGMA_BULLET_MOVES, change
            assert (before["eligibility"], after["eligibility"]) == ("unknown", "blocked")
            moves.append(change)
        elif before != after:
            reason_changes.append(change)
        if row["id"] == "ead832c2-5d4b-4157-9910-24e1d8d9595d":
            assert after["eligibility"] == "unknown", change
            issue11 = change
    assert len(rows) == 658
    assert before_counts == {"blocked": 49, "eligible": 271, "unknown": 338}
    assert after_counts == {"blocked": 52, "eligible": 271, "unknown": 335}
    assert {row["id"] for row in moves} == FIGMA_BULLET_MOVES
    assert issue11 is not None
    print(json.dumps({
        "baseline": BASE,
        "snapshot_sha256": hashlib.sha256(data).hexdigest(),
        "rows": len(rows),
        "before_counts": dict(before_counts),
        "after_counts": dict(after_counts),
        "all_decision_changes": moves,
        "all_reason_only_changes": reason_changes,
        "issue11": issue11,
    }, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
