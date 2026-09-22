import hashlib

import pytest

from scraper.forward_scoring_harness import (
    canonical_json,
    parse_verdict,
    summarize_manifest,
)


def _row(part, locator, gold, score, answer, confidence, *, run=1):
    frozen = {
        "posting": {"id": locator, "jd_text": f"Public JD {locator}"},
        "profile": {},
        "history": [],
    }
    return {
        "part": part,
        "locator": locator,
        "frozen_input": frozen,
        "input_sha256": hashlib.sha256(canonical_json(frozen).encode()).hexdigest(),
        "gold": {"verbatim": gold, "label": parse_verdict(gold)},
        "reference": {
            "fit_score": score,
            "latency_seconds": 2.0,
            "cost_per_row_usd": None,
        },
        "jev": [
            {
                "run": run,
                "answer": answer,
                "confidence": confidence,
                "latency_seconds": 0.5,
                "cost_usd": 0.0001,
            }
        ],
    }


@pytest.mark.parametrize(
    ("verdict", "label"),
    [
        ("Pursue", "Pursue"),
        ("Pursue (with stack question mark)", "Pursue"),
        ("Low pursue", "Pursue"),
        ("Maybe (leaning yes)", "Maybe"),
        ("Very low maybe", "Maybe"),
        ("Strong maybe", "Maybe"),
        ("Low maybe", "Maybe"),
        ("No", "No"),
        ("Probably pursue", None),
    ],
)
def test_parse_verdict_is_explicit_and_qualifier_preserving(verdict, label):
    assert parse_verdict(verdict) == label


def test_summary_recomputes_parts_curve_cost_latency_and_prefilter_verdict():
    rows = [
        _row(1, "one", "Pursue", 80, "pursue", 0.90),
        _row(1, "two", "Maybe", 60, "maybe", 0.80),
        _row(1, "three", "No", 20, "no", 0.95),
        _row(2, "four", "Pursue", 80, "maybe", 0.90),
        _row(2, "five", "Maybe", 60, "no", 0.60),
        _row(2, "six", "No", 20, "no", 0.95),
    ]
    rows.append(_row(2, "seven", "No", 20, "no", 0.95))
    for index in range(21):
        rows.append(
            _row(1 if index % 2 else 2, f"extra-{index}", "Maybe", 60, "maybe", 0.90)
        )
    summary = summarize_manifest({"schema_version": 1, "rows": rows})

    run = summary["runs"][0]
    assert run["parts"]["1"]["jev"]["exact_hits"] == 13
    assert run["parts"]["2"]["jev"]["exact_hits"] == 13
    assert run["pooled"]["jev"]["predicted_no"] == 3
    assert run["threshold_curve"][0]["floor"] == 0.5
    assert run["threshold_curve"][-1]["floor"] == 0.95
    assert run["cost_latency"]["jev"]["cost_per_row_usd"] == pytest.approx(0.0001)
    assert run["cost_latency"]["reference"]["cost_per_row_usd"] is None
    assert run["verdict"]["label"] == "PREFILTER-ONLY"


def test_summary_rejects_changed_frozen_input_and_keeps_reruns_separate():
    first = _row(1, "one", "Pursue", 80, "pursue", 0.9)
    second = {**first["jev"][0], "run": 2, "answer": "no"}
    manifest = {"schema_version": 1, "rows": [first]}
    manifest["rows"][0]["jev"].append(second)
    assert [item["run"] for item in summarize_manifest(manifest)["runs"]] == [1, 2]

    manifest["rows"][0]["frozen_input"]["posting"]["jd_text"] = "mutated"
    with pytest.raises(ValueError, match="sha256"):
        summarize_manifest(manifest)
