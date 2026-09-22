"""Offline contract tests for the E5 per-occurrence rerun harness."""

from __future__ import annotations

from scraper import jev_requirement_rerun as rerun


def test_repeated_identical_mentions_have_distinct_sanitized_locators() -> None:
    title = "Backend Engineer"
    text = "C++ is optional. " + ("unrelated context " * 20) + "Later, C++ is required."
    occurrences = [
        occurrence
        for occurrence in rerun.candidate_occurrences("p-1", title, text)
        if occurrence.label == "c++"
    ]

    assert len(occurrences) == 2
    states = [
        rerun.occurrence_state(occurrence, title, text) for occurrence in occurrences
    ]
    assert states[0]["occurrence"]["mention"] == states[1]["occurrence"]["mention"]
    assert states[0]["occurrence"]["start"] != states[1]["occurrence"]["start"]
    assert states[0]["occurrence"]["context"] != states[1]["occurrence"]["context"]
    assert rerun.public_posting_sanitizer(states[0]) == states[0]


def test_set_semantics_reject_forbidden_hit_and_exclude_unasserted_row() -> None:
    forbidden = rerun.Assertion(
        kind="disjoint", expected=frozenset(), forbidden=frozenset({"c#", "c++"})
    )
    unasserted = rerun.Assertion(kind="excluded")

    assert forbidden.evaluate(set()) is True
    assert forbidden.evaluate({"c#"}) is False
    assert unasserted.evaluate(set()) is None
    assert unasserted.evaluate({"team-lead"}) is None


def test_fake_transport_is_shadow_only_and_sweeps_fixed_thresholds(tmp_path) -> None:
    occurrences = rerun.candidate_occurrences(
        "p-1", "Backend Engineer", "C++ is required. Angular is optional."
    )
    sent: list[dict[str, object]] = []

    def transport(payload, _key):
        sent.append(payload)
        return {
            "model": "jev-test",
            "answers": {
                "requirement_verdict": {
                    "type": "choice",
                    "choice": rerun.HARD,
                    "confidence": 0.91,
                    "probabilities": {rerun.HARD: 0.91, rerun.WAIVED: 0.09},
                }
            },
            "usage": {"input_tokens": 20},
        }

    observations = rerun.score_occurrences(
        occurrences,
        {"p-1": ("Backend Engineer", "C++ is required. Angular is optional.")},
        run=1,
        state_dir=tmp_path,
        transport=transport,
    )

    assert len(observations) == len(occurrences) == len(sent)
    assert all(row.acted is False and row.source == "jev" for row in observations)
    assert [row.floor for row in rerun.threshold_curve(observations, {})] == [
        value / 100 for value in range(50, 100, 5)
    ]
    assert all("occurrence" in payload["state"] for payload in sent)


def test_tower_scores_the_same_occurrence_not_the_whole_row() -> None:
    occurrences = rerun.candidate_occurrences(
        "p-1",
        "Backend Engineer",
        "Technologies such as React and Angular are welcome, but Angular is required.",
    )
    angular = [row for row in occurrences if row.label == "angular"]

    assert len(angular) == 2
    assert [row.tower_answer for row in angular] == [rerun.WAIVED, rerun.HARD]


def test_wilson_interval_comes_from_choice_replay_harness() -> None:
    low, high = rerun.wilson(5, 10)
    assert 0.23 < low < 0.24
    assert 0.76 < high < 0.77
