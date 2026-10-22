"""The offline report projects the same clean salary and raw remark as writes."""

import json

from scripts.dryrun_salary import report


def test_report_projects_clean_salary_with_original_remark(tmp_path):
    snapshot = tmp_path / "snapshot.jsonl"
    raw = "$150k–$180k base + equity (we raised $40M)"
    snapshot.write_text(json.dumps({"id": "synthetic", "salary": raw}) + "\n")
    output = report(snapshot)
    after = output.split("## after set:")[1].split("## after null:")[0]
    assert '"salary": "$150k–$180k base"' in after
    assert f'"salary_remark": "{raw}"' in after
    assert "| after | 1 | 0 | 1 |" in output
