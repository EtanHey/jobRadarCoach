import json

from scripts.dryrun_work_mode import report


def test_snapshot_projection_lists_every_change_and_preserves_remote(tmp_path):
    rows = [
        {"id": "attendance", "work_mode": "remote", "remote": True,
         "work_mode_source": "extracted", "raw_jd": "2 days a week in office."},
        {"id": "remote", "work_mode": "remote", "remote": True,
         "work_mode_source": "extracted", "raw_jd": "Fully remote, no required office days."},
    ]
    snapshot = tmp_path / "snapshot.jsonl"
    snapshot.write_text("\n".join(json.dumps(row) for row in rows))
    output = report(snapshot)
    assert "Rows: 2" in output
    assert "| remote | 2 | 1 |" in output
    assert "| hybrid | 0 | 1 |" in output
    changes = json.loads(output.split("```json\n")[1].split("```")[0])
    assert [change["id"] for change in changes] == ["attendance"]
    assert changes[0]["after"] == {
        "work_mode": "hybrid", "remote": None, "work_mode_source": "extracted",
    }
