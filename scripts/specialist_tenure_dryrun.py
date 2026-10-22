"""Replay frozen scoring inputs offline; no providers, credentials or DB access."""

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from classifier.experience import compare_experience


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("report", type=Path)
    args = parser.parse_args()
    # Synthetic duration-only profile: the posting snapshot contains no candidate
    # profile. This reproduces the triage's 3.7-year total, without invented skills.
    profile = {"candidate": {"tenure_years": 3.7}, "fit_signals": []}
    rows = [json.loads(line) for line in args.snapshot.read_text().split("\n") if line]
    counts = Counter()
    changed = []
    for row in rows:
        comparisons = compare_experience(row.get("raw_jd") or "", profile)
        counts["with_years"] += bool(comparisons)
        counts["unknown_duration"] += any(c["assessment"] == "unknown" for c in comparisons)
        payload = (row.get("posting_scores") or {}).get("score_payload") or {}
        seniority = next((r for r in payload.get("reasons", [])
                          if r.get("factor") == "seniority_gap"), None)
        before = seniority.get("assessment") if seniority else None
        after = "unknown" if seniority and any(
            c["assessment"] == "unknown" for c in comparisons
        ) else before
        if before != after:
            changed.append({"id": row["id"], "company": row["company"], "title": row["title"],
                            "before": before, "after": after, "comparisons": comparisons})
        counts[f"before:{before}"] += 1
        counts[f"after:{after}"] += 1
    report = {
        "status": "OFFLINE INPUT REPLAY ONLY; no model rescore or persisted changes",
        "snapshot_sha256": hashlib.sha256(args.snapshot.read_bytes()).hexdigest(),
        "rows": len(rows), "profile": profile, "counts": dict(counts), "changed_rows": changed,
        "limits": "Changes are seniority assessment schema constraints against frozen assessments, "
                  "not new model answers or score deltas. No candidate specialist duration is assumed. "
                  "Rows without frozen scores still receive input comparisons but have no observed before assessment.",
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"rows": len(rows), "counts": dict(counts), "changed_rows": len(changed)}))


if __name__ == "__main__":
    main()
