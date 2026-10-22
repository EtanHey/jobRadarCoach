"""Offline title-seniority projection; no model, database, or service access."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

from classifier.facts import _seniority, normalize
from scraper.seniority import title_seniority


def _legacy_level(row: dict[str, object]) -> tuple[str | None, str | None]:
    # The pre-mission normalizer searched these sources in this order.
    for field, source in (("seniority", "extracted"), ("ats_seniority", "ats"),
                          ("ats_level", "ats"), ("title", "title")):
        level = _seniority(row.get(field))
        if level is not None:
            return level, source
    return None, None


def report(snapshot: Path) -> dict[str, object]:
    content = snapshot.read_bytes()
    rows = [json.loads(line) for line in content.decode().split("\n") if line.strip()]
    counts = {phase: Counter() for phase in ("before", "after")}
    changes = []
    scalar_changes = level_changes = conflicts = explicit_count = 0
    for row in rows:
        explicit = title_seniority(row.get("title"))
        before_level, before_source = _legacy_level(row)
        after = normalize(row)
        counts["before"][before_level or "unknown"] += 1
        counts["after"][after.seniority_level or "unknown"] += 1
        if explicit is None:
            continue
        explicit_count += 1
        conflicts += explicit.remark is not None
        before_fact = (row.get("posting_extractions") or {}).get("facts", {}).get("seniority")
        after_fact = explicit.fact()
        scalar_changes += row.get("seniority") != explicit.value
        level_changes += before_level != after.seniority_level
        before = {"seniority": row.get("seniority"), "fact": before_fact,
                  "level": before_level, "source": before_source}
        projected = {"seniority": explicit.value, "fact": after_fact,
                     "level": after.seniority_level, "source": after.seniority_source}
        if before != projected:
            changes.append({"id": row["id"], "title": row.get("title"),
                            "before": before, "after": projected,
                            "seniority_remark": explicit.remark})
    return {
        "snapshot_sha256": hashlib.sha256(content).hexdigest(), "rows": len(rows),
        "scope": "Title-only projection. Before levels use pre-mission extracted/ATS/title precedence; after levels use current normalize. Stored extraction evidence is compared, not regenerated. No scoring, years inference, backfill, or writes to services.",
        "level_counts": {phase: dict(sorted(values.items())) for phase, values in counts.items()},
        "explicit_title_rows": explicit_count, "conflicting_title_rows": conflicts,
        "scalar_changes": scalar_changes, "level_changes": level_changes,
        "changed_rows": changes, "changed_row_count": len(changes),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.write_text(json.dumps(report(args.snapshot), ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
