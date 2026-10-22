"""Offline frozen-JD replay; no DB, network, inference model, or service access."""
import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path

from scraper.ats_liveness import project_liveness
from scraper.deadlines import SOURCE, extract_deadline


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("report", type=Path)
    parser.add_argument("--now", required=True, help="Frozen zoned ISO timestamp")
    args = parser.parse_args()
    now = datetime.fromisoformat(args.now.replace("Z", "+00:00"))
    if now.tzinfo is None:
        parser.error("--now must include a timezone")
    rows = list(map(json.loads, args.snapshot.read_text().splitlines()))
    changed = []
    normalized_before = normalized_after = unknown = 0
    for row in rows:
        evidence = row.get("liveness") or {}
        before = project_liveness(evidence, now=now)
        if before["state"] == "deadline_passed":
            before["alive"] = None  # #485 behavior before this patch.
        normalized_before += before["application_deadline"] is not None
        extracted = extract_deadline(row.get("raw_jd") or "")
        has_frame = extracted["application_deadline_evidence_quote"] is not None
        unknown += has_frame and extracted["application_deadline"] is None
        patch = extracted if has_frame or evidence.get("application_deadline_source") == SOURCE else {}
        after = project_liveness({**evidence, **patch}, now=now)
        normalized_after += after["application_deadline"] is not None
        if before != after or any(evidence.get(key) != value for key, value in patch.items()):
            changed.append({"id": row["id"], "company": row["company"],
                            "before": before, "after": after, "extracted": extracted})
    report = {"snapshot_sha256": hashlib.sha256(args.snapshot.read_bytes()).hexdigest(),
              "now": args.now, "rows": len(rows), "changed_rows": len(changed),
              "normalized_before": normalized_before, "normalized_after": normalized_after,
              "unknown_deadline_frames": unknown,
              "newly_closed": sum(item["before"]["alive"] is not False and item["after"]["alive"] is False for item in changed),
              "changes": changed}
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({key: value for key, value in report.items() if key != "changes"}))


if __name__ == "__main__":
    main()
