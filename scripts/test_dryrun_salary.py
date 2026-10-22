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


def test_report_preserves_unicode_line_separators_inside_jsonl_records(tmp_path):
    snapshot = tmp_path / "snapshot.jsonl"
    snapshot.write_text(json.dumps({
        "id": "synthetic", "salary": "$150k", "raw_jd": "first\u2028second\u0085third",
    }, ensure_ascii=False) + "\n")
    assert "| after | 1 | 0 | 0 |" in report(snapshot)


def test_report_projects_list_governor_corpus(tmp_path):
    from extractor.test_salary import P9D_SALARY_SPANS

    snapshot = tmp_path / "governors.jsonl"
    snapshot.write_text("\n".join(json.dumps({"id": index, "salary": value})
                                  for index, (value, _) in enumerate(P9D_SALARY_SPANS)))
    output = report(snapshot)
    set_count = sum(span is not None for _, span in P9D_SALARY_SPANS)
    null_count = len(P9D_SALARY_SPANS) - set_count
    remark_count = sum(value != span for value, span in P9D_SALARY_SPANS)
    assert f"| after | {set_count} | {null_count} | {remark_count} |" in output
