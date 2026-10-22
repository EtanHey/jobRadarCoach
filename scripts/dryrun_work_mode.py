"""Project office-attendance normalization over an exported JSONL snapshot, offline."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

from extractor.evidence import attendance_evidence


def report(snapshot: Path) -> str:
    rows = [json.loads(line) for line in snapshot.read_text().splitlines() if line.strip()]
    before: Counter[str] = Counter()
    after: Counter[str] = Counter()
    changed = []
    for row in rows:
        old = {key: row.get(key) for key in ("work_mode", "remote", "work_mode_source")}
        new = dict(old)
        evidence = attendance_evidence(row.get("raw_jd") or "")
        if evidence is not None:
            mode, quote = evidence
            new.update(work_mode=mode, remote=False if mode == "on-site" else None,
                       work_mode_source="extracted")
        before[old["work_mode"] or "unknown"] += 1
        after[new["work_mode"] or "unknown"] += 1
        if old != new:
            changed.append({
                "id": row["id"], "company": row.get("company"), "title": row.get("title"),
                "before": old, "after": new, "evidence": quote,
            })
    lines = [
        "# WORKMODE offline snapshot projection", "",
        f"Rows: {len(rows)}",
        f"Snapshot SHA-256: {hashlib.sha256(snapshot.read_bytes()).hexdigest()}", "",
        "Projects the deterministic attendance override used by extraction persistence.",
        "No model, database, network, or service calls. Other posting fields are unchanged.",
        "This is a policy replay, not a backfill or a fresh model extraction.", "",
        "| Work mode | Before | After |", "|---|---:|---:|",
    ]
    for mode in sorted(before.keys() | after.keys()):
        lines.append(f"| {mode} | {before[mode]} | {after[mode]} |")
    lines.extend(["", f"Changed rows: {len(changed)}. All changes follow.", "", "```json"])
    lines.append(json.dumps(changed, ensure_ascii=False, indent=2))
    lines.extend(["```", ""])
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.write_text(report(args.snapshot))


if __name__ == "__main__":
    main()
