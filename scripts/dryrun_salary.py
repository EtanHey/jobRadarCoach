"""Read-only salary policy projection over an exported JSONL snapshot."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from extractor.evidence import has_numeric_salary


def report(snapshot: Path) -> str:
    rows = [
        json.loads(line) for line in snapshot.read_text().splitlines() if line.strip()
    ]
    groups: dict[str, list[dict[str, object]]] = {}
    for phase in ("before", "after"):
        for category in ("set", "null", "remark"):
            groups[f"{phase} {category}"] = []
    for row in rows:
        salary = row.get("salary")
        remark = (
            (row.get("posting_extractions") or {}).get("facts", {}).get("salary_remark")
        )
        for phase in ("before", "after"):
            value, note = salary, remark
            if phase == "after" and isinstance(value, str) and value.strip():
                if not has_numeric_salary(value):
                    value, note = None, value
            sample = {"id": row["id"], "salary": value, "salary_remark": note}
            groups[f"{phase} {'set' if value else 'null'}"].append(sample)
            if note:
                groups[f"{phase} remark"].append(sample)
    lines = [
        "# P9b salary dry run",
        "",
        f"Rows: {len(rows)}",
        f"Snapshot SHA-256: {hashlib.sha256(snapshot.read_bytes()).hexdigest()}",
        "",
        "Read-only projection of displayed posting salary through has_numeric_salary; no LLM, DB, or service calls.",
        "Remarks overlap the null category. Existing numeric salaries survive; nonnumeric strings become raw remarks.",
        "This projects the policy over all stored salaries, not a backfill or a claim that every source quote was revalidated.",
        "Runtime persistence clears a preexisting salary only when it matches the rejected extraction value; unrelated harvested amounts remain intact.",
        "The UI still reads nullable postings.salary; raw remarks live additively in posting_extractions.facts.salary_remark.",
        "",
        "| Phase | Salary set | Salary null | Remark |",
        "|---|---:|---:|---:|",
    ]
    for phase in ("before", "after"):
        lines.append(
            f"| {phase} | "
            + " | ".join(
                str(len(groups[f"{phase} {c}"])) for c in ("set", "null", "remark")
            )
            + " |"
        )
    for key, samples in groups.items():
        lines.extend(
            [
                "",
                f"## {key}: {len(samples)} rows; first {min(10, len(samples))} samples",
                "",
            ]
        )
        if samples:
            lines.extend(
                [
                    "```json",
                    json.dumps(samples[:10], ensure_ascii=False, indent=2),
                    "```",
                ]
            )
        else:
            lines.append("No rows in this category; no samples available.")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.write_text(report(args.snapshot))


if __name__ == "__main__":
    main()
