from __future__ import annotations

import json

from scripts.seniority_dryrun import report


def test_report_lists_every_changed_row_without_changing_snapshot(tmp_path):
    snapshot = tmp_path / "snapshot.jsonl"
    rows = [
        {"id": "senior", "title": "Senior Software Engineer", "seniority": "Software Engineer"},
        {"id": "junior", "title": "מפתח ג'וניור", "seniority": "Senior"},
        {"id": "unchanged", "title": "Engineer", "seniority": "Mid"},
    ]
    content = "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n"
    snapshot.write_text(content)

    result = report(snapshot)

    assert result["rows"] == 3
    assert result["scalar_changes"] == result["changed_row_count"] == 2
    assert result["level_changes"] == 1
    assert result["level_counts"] == {
        "before": {"mid": 1, "senior": 2}, "after": {"junior": 1, "mid": 1, "senior": 1},
    }
    assert [row["id"] for row in result["changed_rows"]] == ["senior", "junior"]
    assert result["changed_rows"][0]["after"]["fact"] == {
        "value": "Senior", "evidence_quote": "Senior Software Engineer",
    }
    assert snapshot.read_text() == content
