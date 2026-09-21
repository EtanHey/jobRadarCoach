"""Offline tests for the E5 requirement replay harness."""

from __future__ import annotations

from scraper import jev_requirement_replay as replay


def test_load_cases_imports_33_parametrize_rows_and_five_fixture_rows() -> None:
    cases = replay.load_cases()
    assert len(cases) == 38
    assert sum(case.source == "test_harvest.py" for case in cases) == 33
    assert (
        sum(case.source == "job-radar-rescore-2026-08-11.json" for case in cases) == 5
    )
    assert all(
        case.state and case.current_regex_verdict == case.repo_label for case in cases
    )
    assert all(
        set(case.expected_negative_hits) <= set(case.current_negative_hits)
        for case in cases
    )
    assert "principal" in cases[2].state["candidate_mentions"]
    assert replay.public_posting_sanitizer(cases[0].state) == cases[0].state


def test_fake_replay_is_end_to_end_and_sweeps_thresholds(tmp_path) -> None:
    cases = replay.load_cases()[:2]

    def fake_transport(payload, _key):
        return {
            "model": "jev-recorded",
            "answers": {
                "requirement_verdict": {
                    "type": "choice",
                    "choice": "hard_requirement",
                    "confidence": 0.9,
                    "probabilities": {
                        "hard_requirement": 0.95,
                        "waived_or_no_match": 0.05,
                    },
                }
            },
            "usage": {"input_tokens": 20, "output_tokens": 5},
        }

    result = replay.run_replay(
        cases,
        runs=3,
        sanitizer=lambda value: value,
        transport=fake_transport,
        log_path=tmp_path / "decisions.jsonl",
        usage_path=tmp_path / "usage.jsonl",
    )
    assert result.planned_calls == 6
    assert result.actual_calls == 6
    assert result.models == {"jev-recorded"}
    assert [row.floor for row in result.curve] == [
        value / 100 for value in range(50, 100, 5)
    ]
    assert len(result.run_summaries) == 3
