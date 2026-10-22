"""Frozen replay reports every changed row without touching external resources."""
import json
from pathlib import Path
import subprocess
import sys


def test_snapshot_replay_counts_and_every_changed_row(tmp_path):
    snapshot, report = tmp_path / "snapshot.jsonl", tmp_path / "report.json"
    checked = {"alive": True, "liveness_checked_at": "2026-10-22T09:30:00Z"}
    rows = [
        {"id": "closed", "company": "Synthetic", "raw_jd": "Application deadline: 2026-10-18", "liveness": checked},
        {"id": "unknown", "company": "Synthetic", "raw_jd": "Applications close on October 18th.", "liveness": checked},
        {"id": "none", "company": "Synthetic", "raw_jd": "Project deadline: 2026-10-18", "liveness": checked},
    ]
    snapshot.write_text("\n".join(map(json.dumps, rows)))
    subprocess.run([sys.executable, "-m", "scripts.deadline_dryrun", str(snapshot), str(report),
                    "--now", "2026-10-22T10:00:00Z"], cwd=Path(__file__).parents[1], check=True, capture_output=True)
    result = json.loads(report.read_text())
    assert (result["rows"], result["changed_rows"], result["normalized_before"], result["normalized_after"],
            result["unknown_deadline_frames"], result["newly_closed"]) == (3, 2, 0, 1, 1, 1)
    assert [row["id"] for row in result["changes"]] == ["closed", "unknown"]
    assert result["changes"][0]["before"]["alive"] is True
    assert result["changes"][0]["after"]["alive"] is False
    assert result["changes"][1]["after"]["alive"] is True
