"""Offline required-stack policy replay; no model, database, or service access."""

import argparse
from collections import Counter
import copy
import hashlib
import json
from pathlib import Path

from classifier.projection import profile_contract
from scraper.stack_requirements import apply_stack_gap_guard


def report(snapshot, profile):
    raw = snapshot.read_bytes()
    rows = [json.loads(line) for line in raw.splitlines() if line.strip()]
    counts = {phase: Counter() for phase in ("before", "after")}
    changes = []
    for row in rows:
        before = (row.get("posting_scores") or {}).get("score_payload")
        if not before or not before.get("recommendation") or not any(
            r.get("factor") == "stack_domain_evidence" for r in before.get("reasons", [])
        ):
            counts["before"]["unscored"] += 1
            counts["after"]["unscored"] += 1
            continue
        after = apply_stack_gap_guard(copy.deepcopy(before), row, profile)
        counts["before"][before["recommendation"]] += 1
        counts["after"][after["recommendation"]] += 1
        if after != before:
            changes.append({
                "id": row["id"], "company": row["company"],
                "before": before["recommendation"], "after": after["recommendation"],
                "reason": next(r["detail"] for r in after["reasons"]
                               if r["factor"] == "stack_domain_evidence"),
                "changes": {key: {"before": before[key], "after": value}
                            for key, value in after.items() if before.get(key) != value},
            })
    return "\n".join([
        "# STACK offline snapshot replay", "", "STATUS: OFFLINE; no backfill applied.",
        f"Rows: {len(rows)}; changed rows: {len(changes)}",
        f"Snapshot SHA-256: {hashlib.sha256(raw).hexdigest()}", "",
        "Profile SHA-256: " + hashlib.sha256(
            json.dumps(profile, sort_keys=True).encode()
        ).hexdigest(), "",
        "Existing score payloads passed through the new deterministic guard; no rescoring.",
        "Profile is supplied separately; the snapshot does not freeze candidate evidence.",
        "No numeric score changes. Missing evidence is unconfirmed, never a claim of inability.",
        "", "## Recommendation counts", "", "```json",
        json.dumps(counts, indent=2, sort_keys=True), "```", "",
        "## Every changed row", "", "```json",
        json.dumps(changes, indent=2, ensure_ascii=False), "```", "",
    ])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("profile", type=Path, help="Frozen DB profile snapshot JSON (contract_version=1)")
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    profile = profile_contract(json.loads(args.profile.read_text()))
    args.output.write_text(report(args.snapshot, profile))


if __name__ == "__main__":
    main()
