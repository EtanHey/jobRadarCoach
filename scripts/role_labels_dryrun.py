"""Replay stored role labels offline; never connect to a provider or database."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

from classifier.persistence import _labels


def report(snapshot: Path) -> str:
    rows = [json.loads(line) for line in snapshot.read_text().splitlines() if line.strip()]
    counts = {phase: Counter() for phase in ("before", "after")}
    changes = []
    unscored = 0
    for row in rows:
        score = row.get("posting_scores")
        if score is None:
            unscored += 1
            continue
        before = score["labels"]["role_type"]
        after = _labels(score["score_payload"], row)["role_type"]
        counts["before"][before] += 1
        counts["after"][after] += 1
        if before != after:
            changes.append({
                "id": row["id"], "company": row["company"], "title": row["title"],
                "before": before, "after": after,
            })
    lines = [
        "# ROLELEAK offline snapshot replay", "",
        f"Rows: {len(rows)}; scored: {len(rows) - unscored}; unscored: {unscored}.",
        f"Snapshot SHA-256: {hashlib.sha256(snapshot.read_bytes()).hexdigest()}", "",
        "Before uses the stored role_type; after uses the new persistence policy on the same posting.",
        "Only the advertised posting title supplies role identity. Unrecognized or ambiguous titles yield null.",
        "Unscored rows stay unscored. Scores, fit reasoning, extraction facts and posting fields are unchanged.",
        "This is a local policy projection, not a model replay, production backfill or runtime verification.", "",
    ]
    for label in (None, "fullstack", "frontend", "ai", "voice"):
        lines.append(f"{label or 'null'}: {counts['before'][label]} -> {counts['after'][label]}")
    lines.extend(["", f"Changed rows: {len(changes)}. Every changed row follows.", "", "```json"])
    lines.extend([json.dumps(changes, ensure_ascii=False, indent=2), "```", ""])
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.write_text(report(args.snapshot))


if __name__ == "__main__":
    main()
