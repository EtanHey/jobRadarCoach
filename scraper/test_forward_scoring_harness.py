import hashlib

import pytest

from scraper.forward_scoring_harness import (
    canonical_json,
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
        "gold": {"verbatim": gold, "label": gold.split()[0]},
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


def _manifest(rows):
    expected = {row["locator"]: row["part"] for row in rows}
    dropped = []
    for part, planned in ((1, 20), (2, 10), (3, 10)):
        missing = planned - sum(value == part for value in expected.values())
        for index in range(missing):
            locator = f"planned-part{part}-{index + 1}"
            expected[locator] = part
            dropped.append(
                {"locator": locator, "part": part, "reason": "fixture exclusion"}
            )
    return {
        "schema_version": 1,
        "expected_locators": expected,
        "dropped": dropped,
        "rows": rows,
    }


def test_summary_recomputes_parts_and_cost_latency():
    rows = [
        _row(1, "one", "Pursue", 80, "pursue", 0.90),
        _row(2, "two", "No", 20, "no", 0.95),
        _row(3, "three", "Maybe", 50, "maybe", 0.90),
    ]
    summary = summarize_manifest(_manifest(rows))

    run = summary["runs"][0]
    assert run["parts"]["1"]["jev"]["exact_hits"] == 1
    assert run["parts"]["2"]["jev"]["exact_hits"] == 1
    assert run["parts"]["3"]["jev"]["exact_hits"] == 1
    assert run["subtotals"]["non_radar"]["jev"]["n"] == 2
    assert run["cost_latency"]["jev"]["cost_per_row_usd"] == pytest.approx(0.0001)
    assert run["cost_latency"]["reference"]["cost_per_row_usd"] is None


@pytest.mark.parametrize(
    ("target", "field", "value"),
    [
        ("reference", "latency_seconds", float("nan")),
        ("jev", "latency_seconds", True),
        ("jev", "cost_usd", -1),
    ],
)
def test_summary_rejects_non_finite_measurements(target, field, value):
    row = _row(1, "one", "Pursue", 80, "pursue", 0.9)
    measurement = row["reference"] if target == "reference" else row["jev"][0]
    measurement[field] = value

    with pytest.raises(
        (TypeError, ValueError), match=f"{field} must be a finite non-negative number"
    ):
        summarize_manifest(
            _manifest(
                [
                    row,
                    _row(2, "two", "No", 20, "no", 0.9),
                    _row(3, "three", "Maybe", 50, "maybe", 0.9),
                ]
            )
        )


def test_summary_requires_expected_locator_drop_ledger_and_all_parts():
    rows = [
        _row(1, "one", "Pursue", 80, "pursue", 0.9),
        _row(2, "two", "No", 20, "no", 0.9),
        _row(3, "three", "Maybe", 50, "maybe", 0.9),
    ]
    manifest = _manifest(rows)
    omitted = manifest["dropped"].pop()
    with pytest.raises(ValueError, match="included or explicitly dropped"):
        summarize_manifest(manifest)

    manifest["dropped"].append(omitted)
    assert summarize_manifest(manifest)["row_count"] == 3
    assert len(manifest["expected_locators"]) == 40
    missing_parts = _manifest([rows[0]])
    with pytest.raises(
        ValueError, match="included rows must contain parts 1, 2, and 3"
    ):
        summarize_manifest(missing_parts)
    manifest["rows"][0]["frozen_input"]["posting"]["jd_text"] = "mutated"
    with pytest.raises(ValueError, match="sha256"):
        summarize_manifest(manifest)


@pytest.mark.parametrize("bad_part", [True, 1.0])
@pytest.mark.parametrize("target", ["included", "dropped"])
def test_summary_rejects_non_integer_included_and_dropped_parts(target, bad_part):
    rows = [
        _row(1, "one", "Pursue", 80, "pursue", 0.9),
        _row(2, "two", "No", 20, "no", 0.9),
        _row(3, "three", "Maybe", 50, "maybe", 0.9),
    ]
    manifest = _manifest(rows)
    if target == "included":
        manifest["rows"][0]["part"] = bad_part
    else:
        manifest["dropped"][0]["part"] = bad_part

    with pytest.raises(
        ValueError, match=f"{target} row part must be integer 1, 2, or 3"
    ):
        summarize_manifest(manifest)


def test_summary_rejects_wrong_planned_total_and_part_distribution():
    rows = [
        _row(1, "one", "Pursue", 80, "pursue", 0.9),
        _row(2, "two", "No", 20, "no", 0.9),
        _row(3, "three", "Maybe", 50, "maybe", 0.9),
    ]
    too_small = {
        "schema_version": 1,
        "expected_locators": {row["locator"]: row["part"] for row in rows},
        "dropped": [],
        "rows": rows,
    }
    with pytest.raises(ValueError, match="exactly 20/10/10 planned locators"):
        summarize_manifest(too_small)

    wrong_distribution = _manifest(rows)
    part1_locator = next(
        locator
        for locator, part in wrong_distribution["expected_locators"].items()
        if part == 1 and locator != "one"
    )
    wrong_distribution["expected_locators"][part1_locator] = 2
    with pytest.raises(ValueError, match="exactly 20/10/10 planned locators"):
        summarize_manifest(wrong_distribution)
