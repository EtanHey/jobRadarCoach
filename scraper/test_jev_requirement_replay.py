"""Offline tests for the E5 requirement replay harness."""

from __future__ import annotations

import json

from scraper import jev_requirement_replay as replay


def fake_response(payload, _key):
    occurrence = payload["state"]["occurrence"].casefold()
    answer = replay.HARD if occurrence in {"principal", "docker"} else replay.WAIVED
    return {
        "model": "jev-recorded",
        "answers": {"requirement_verdict": {"type": "choice", "choice": answer, "confidence": 0.9,
                                               "probabilities": {answer: 0.95, (replay.WAIVED if answer == replay.HARD else replay.HARD): 0.05}}},
        "usage": {"input_tokens": 20, "output_tokens": 5},
    }


def test_load_cases_preserves_source_assertion_semantics_and_occurrences() -> None:
    cases = replay.load_cases()
    assert len(cases) == 38
    assert sum(case.source == "test_harvest.py" for case in cases) == 33
    assert sum(case.source == replay.FIXTURE.name for case in cases) == 5
    assert all(set(case.expected_negative_hits) <= set(case.current_negative_hits) for case in cases)
    assert cases[2].assertion == "exact"
    assert {(row.label, row.mention.casefold()) for row in cases[2].occurrences} >= {
        ("principal", "principal"), ("c++", "c++")}
    assert next(case for case in cases if case.id == "walls-1").assertion == "subset"
    assert next(case for case in cases if case.id.startswith("fixture-")).assertion == "exact"


def test_fake_replay_calls_once_per_candidate_occurrence_and_reconstructs_sets(tmp_path) -> None:
    cases = replay.load_cases()[2:3]
    expected_calls = len(cases[0].occurrences) * 3
    result = replay.run_replay(cases, runs=3, sanitizer=replay.public_posting_sanitizer,
                               transport=fake_response, log_path=tmp_path / "d.jsonl", usage_path=tmp_path / "u.jsonl")
    assert result.planned_calls == expected_calls == result.actual_calls
    assert len(result.decisions) == expected_calls
    assert result.models == {"jev-recorded"}
    assert [row.floor for row in result.curve] == [value / 100 for value in range(50, 100, 5)]
    per_run = [row for row in result.decisions if row.run == 1]
    assert replay._predicted(per_run) == {"principal"}
    assert cases[0].passes(replay._predicted(per_run)) is False
    assert all(row.acted is False for row in result.decisions)


def test_report_states_withdrawal_and_row_level_pass_bar(tmp_path) -> None:
    case = replay.load_cases()[0]
    result = replay.run_replay([case], runs=3, sanitizer=replay.public_posting_sanitizer,
                               transport=fake_response, log_path=tmp_path / "d.jsonl", usage_path=tmp_path / "u.jsonl")
    report = replay.render_report(result)
    assert "earlier E5 numbers are withdrawn" in report
    assert "Planned / actual calls" in report
    assert "0.50" in report and "0.95" in report
    assert "| Floor | Run 1 | Run 2 | Run 3 |" in report
    assert "Exact rows require set equality" in report


def test_main_refuses_non_shadow_mode(monkeypatch, capsys) -> None:
    monkeypatch.setenv("JEV_SITE_JRC_E5", "on")
    assert replay.main(["--plan"]) == 2
    assert "requires effective mode shadow" in capsys.readouterr().out


def test_all_decision_log_rows_are_shadow(tmp_path) -> None:
    case = replay.load_cases()[2]
    log = tmp_path / "d.jsonl"
    replay.run_replay([case], runs=1, sanitizer=replay.public_posting_sanitizer,
                      transport=fake_response, log_path=log, usage_path=tmp_path / "u.jsonl")
    assert all(json.loads(line)["acted"] is False for line in log.read_text().splitlines())
