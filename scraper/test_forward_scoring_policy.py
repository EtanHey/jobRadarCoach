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
        "professional_profile": {"projection_version": 1},
        "public_posting": {
            "id": str(index),
            "company": "Acme",
            "title": f"Engineer {index}",
            "location": "Remote",
            "jd_text": "x" * 200,
        },
        "history_policy": "excluded",
    }
    no = gold == "No"
    return {
        "part": part,
        "locator": f"row-{index}",
        "frozen_input": frozen,
        "input_sha256": hashlib.sha256(canonical_json(frozen).encode()).hexdigest(),
        "gold": {"verbatim": gold, "label": gold},
        "reference": {
            "fit_score": 20 if no else 60,
            "latency_seconds": 2.0,
            "cost_per_row_usd": None,
        },
        "jev": [
            {
                "run": 1,
                "answer": "no" if no else "maybe",
                "confidence": 0.9,
                "latency_seconds": 0.5,
                "cost_usd": 0.0001,
            }
        ],
    }


def _manifest() -> dict[str, object]:
    rows = [
        *[_row(index, 1, "Maybe" if index < 20 else "No") for index in range(1, 21)],
        *[_row(index, 2, "Maybe" if index < 29 else "No") for index in range(21, 31)],
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
    assert intervals["eligible_positive"]["denominator"] == 27
    assert intervals["actual_prefiltered"]["denominator"] == 3
    assert intervals["eligible_positive"]["wilson_95"][1] <= 0.20
    assert intervals["actual_prefiltered"]["wilson_95"][1] > 0.20
    assert [point["floor"] for point in run["threshold_curve"]] == [
        value / 100 for value in range(50, 100, 5)
    ]


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
    assert "### Part 1" in report and "### Part 2" in report
    assert "eligible positive | 0/27" in report
    assert "actual prefiltered | 0/3" in report
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

    assert "29 executed labels (30 planned)" in report
    assert "Only 2 executed labels are clear No's" in report
