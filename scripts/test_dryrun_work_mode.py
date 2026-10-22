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


def test_full_office_schedule_and_other_role_scope_in_projection(tmp_path):
    rows = [
        {"id": "full-office", "work_mode": "remote", "remote": True,
         "raw_jd": "This role requires five office days per week."},
        {"id": "other-role", "work_mode": "remote", "remote": True,
         "raw_jd": "This role is remote. Some other teams have a hybrid work policy."},
    ]
    snapshot = tmp_path / "snapshot.jsonl"
    snapshot.write_text("\n".join(json.dumps(row) for row in rows))
    output = report(snapshot)
    changes = json.loads(output.split("```json\n")[1].split("```")[0])
    assert [change["id"] for change in changes] == ["full-office"]
    assert changes[0]["after"] == {
        "work_mode": "on-site", "remote": False, "work_mode_source": "extracted",
    }


def test_unresolved_arrangement_clears_stored_mode_in_projection(tmp_path):
    snapshot = tmp_path / "snapshot.jsonl"
    snapshot.write_text(json.dumps({
        "id": "alternatives", "work_mode": "remote", "remote": True,
        "work_mode_source": "structured",
        "raw_jd": "This role offers remote or hybrid work arrangements.",
    }))
    output = report(snapshot)
    changes = json.loads(output.split("```json\n")[1].split("```")[0])
    assert changes[0]["after"] == {
        "work_mode": None, "remote": None, "work_mode_source": None,
    }
