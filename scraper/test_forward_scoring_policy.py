import hashlib

import pytest

from scraper.forward_scoring_harness import canonical_json
from scraper.forward_scoring_policy import (
    parse_verdict,
    render_report,
    summarize_forward,
)


def _row(index: int, part: int, gold: str) -> dict[str, object]:
    frozen = {
        "hosted_payload": {
            "professional_profile": {"projection_version": 1},
            "public_posting": {
                "id": str(index),
                "company": "Acme",
                "title": f"Engineer {index}",
                "location": "Remote",
                "jd_text": "x" * 200,
            },
        },
        "reference_validation_profile": {},
        "history_policy": "excluded",
    }
    score = {"Pursue": 80, "Maybe": 60, "No": 20}[gold]
    answer = gold.casefold()
    return {
        "part": part,
        "locator": f"row-{index}",
        "frozen_input": frozen,
        "input_sha256": hashlib.sha256(canonical_json(frozen).encode()).hexdigest(),
        "gold": {"verbatim": gold, "label": gold},
        "reference": {
            "fit_score": score,
            "latency_seconds": 2.0,
            "cost_per_row_usd": None,
        },
        "jev": [
            {
                "run": 1,
                "answer": answer,
                "confidence": 0.9,
                "latency_seconds": 0.5,
                "cost_usd": 0.0001,
            }
        ],
    }


def _manifest() -> dict[str, object]:
    rows = [
        *[_row(index, 1, "Maybe") for index in range(1, 21)],
        *[_row(index, 2, "Maybe") for index in range(21, 31)],
        *[_row(index, 3, "Pursue") for index in range(31, 34)],
        *[_row(index, 3, "Maybe") for index in range(34, 37)],
        *[_row(index, 3, "No") for index in range(37, 41)],
    ]
    return {
        "schema_version": 1,
        "expected_locators": {row["locator"]: row["part"] for row in rows},
        "dropped": [],
        "rows": rows,
        "execution": {
            "codex_cli_version": "codex-cli 0.154.0",
            "production_codex_pin": "codex-cli 0.153.4",
        },
    }


@pytest.mark.parametrize(
    ("verdict", "label"),
    [
        ("Pursue (with stack question mark)", "Pursue"),
        ("Low pursue", "Pursue"),
        ("Very low maybe", "Maybe"),
        ("Strong maybe", "Maybe"),
        ("Low maybe", "Maybe"),
        ("No", "No"),
        ("Probably pursue", None),
    ],
)
def test_parse_verdict_uses_only_the_precommitted_mapping(verdict, label):
    assert parse_verdict(verdict) == label


def test_supplementary_prefilter_interval_does_not_change_acceptance_bar():
    run = summarize_forward(_manifest())["runs"][0]

    assert run["verdict"]["label"] == "PREFILTER-ONLY"
    assert run["verdict"]["metric"] == "eligible_positive_wilson_upper"
    intervals = run["false_rejection_intervals"]
    assert intervals["eligible_positive"]["denominator"] == 36
    assert intervals["actual_prefiltered"]["denominator"] == 4
    assert intervals["eligible_positive"]["wilson_95"][1] <= 0.20
    assert intervals["actual_prefiltered"]["wilson_95"][1] > 0.20
    assert {
        label: sum(
            row["gold"]["label"] == label
            for row in _manifest()["rows"]
            if row["part"] == 3
        )
        for label in ("Pursue", "Maybe", "No")
    } == {"Pursue": 3, "Maybe": 3, "No": 4}
    assert [point["floor"] for point in run["threshold_curve"]] == [
        value / 100 for value in range(50, 100, 5)
    ]
    assert set(run["threshold_curve"][0]["parts"]) == {"1", "2", "3"}
    assert run["threshold_curve"][0]["non_radar"] == 1.0


@pytest.mark.parametrize(
    ("verbatim", "declared"),
    [("No", "Maybe"), ("Probably pursue", "Pursue")],
)
def test_summary_rejects_gold_that_does_not_match_verbatim_parser(verbatim, declared):
    manifest = _manifest()
    manifest["rows"][0]["gold"] = {"verbatim": verbatim, "label": declared}

    with pytest.raises(ValueError, match="verbatim verdict"):
        summarize_forward(manifest)


def test_report_discloses_runtime_privacy_parts_and_both_intervals():
    report = render_report(_manifest())

    assert report.count("VERDICT: **") == 1
    assert all(f"### Part {part}" in report for part in (1, 2, 3))
    assert "### Non-radar subtotal (Parts 2+3)" in report
    assert "### Pooled" in report
    assert "eligible positive | 0/36" in report
    assert "actual prefiltered | 0/4" in report
    assert "codex-cli 0.154.0" in report and "codex-cli 0.153.4" in report
    assert "application history and truth labels were excluded" in report
    assert report.index("| jev |") < report.index("**reference confusion**")


def test_report_derives_executed_and_clear_no_counts_after_drop():
    manifest = _manifest()
    dropped = manifest["rows"].pop()
    manifest["dropped"] = [
        {"locator": dropped["locator"], "part": dropped["part"], "reason": "ambiguous"}
    ]

    report = render_report(manifest)

    assert "39 executed labels (40 planned)" in report
    assert "Only 3 executed labels are clear No's" in report


def test_prefilter_requires_four_confident_no_predictions():
    manifest = _manifest()
    manifest["rows"][-1]["jev"][0]["answer"] = "maybe"

    verdict = summarize_forward(manifest)["runs"][0]["verdict"]

    assert verdict == {"label": "NO-GO", "metric": "confident_no_count", "value": 3}
