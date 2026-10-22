"""Replay gate decisions on frozen JSONL, offline; never connects to a database."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import subprocess

from scraper.jd_quality import jd_quality_rule
from scraper.relevance import _classified_gate, PURSUIT_STATUSES


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("report", type=Path)
    parser.add_argument("--base", required=True, help="Local commit before the quality gate")
    args = parser.parse_args()
    # The baseline is local repository code, not text from the untrusted snapshot.
    source = subprocess.run(
        ["git", "show", f"{args.base}:scraper/relevance.py"],
        check=True, capture_output=True, text=True,
    ).stdout
    baseline = {}
    exec(compile(source, "baseline-relevance.py", "exec"), baseline)
    before, after, quality = Counter(), Counter(), Counter()
    changed = []
    rows = [json.loads(line) for line in args.snapshot.read_text().splitlines() if line.strip()]
    for row in rows:
        gate = row.get("relevance_gate") or {}
        reason = jd_quality_rule(row.get("raw_jd"))
        quality[reason or "unflagged"] += 1
        protected = gate.get("override") or (row.get("posting_status") or {}).get("status") in PURSUIT_STATUSES
        captured = (row["id"], row["title"], row.get("raw_jd"), bool(row.get("posting_scores")), gate)
        old = gate.get("rule") if protected else baseline["_classified_gate"](captured)["rule"]
        new = gate.get("rule") if protected else _classified_gate(captured)["rule"]
        before[old or "unfiltered"] += 1
        after[new or "unfiltered"] += 1
        if old != new:
            score = row.get("posting_scores") or {}
            changed.append(dict(id=row["id"], company=row["company"], title=row["title"],
                                before=old, after=new, previous_score=score.get("score"),
                                previous_recommendation=score.get("recommendation")))
    result = dict(status="OFFLINE ONLY; no DB/provider access or score writes",
                  snapshot_sha256=hashlib.sha256(args.snapshot.read_bytes()).hexdigest(),
                  base=args.base, rows=len(rows), before=dict(before), after=dict(after),
                  quality=dict(quality), changed=changed,
                  limits="Rule decisions only; version-only changes omitted. Owner overrides and pursued rows preserved.")
    args.report.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({key: result[key] for key in ("rows", "before", "after", "quality")}))


if __name__ == "__main__":
    main()
