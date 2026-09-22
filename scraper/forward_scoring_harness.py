"""Recompute forward-scoring measurements from one immutable manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import statistics
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

LABELS = ("Pursue", "Maybe", "No")
FIXED_FLOOR = 0.70
FLOORS = tuple(value / 100 for value in range(50, 100, 5))


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def parse_verdict(verbatim: str) -> str | None:
    """Map only Etan's explicit verdict head; qualifiers never change its class."""
    plain = re.sub(r"[*_`]", "", verbatim).strip().casefold()
    patterns = (
        ("Pursue", r"^(?:low\s+)?pursue(?:\s*\([^)]*\))?$"),
        ("Maybe", r"^(?:(?:very\s+)?low\s+|strong\s+)?maybe(?:\s*\([^)]*\))?$"),
        ("No", r"^no(?:\s*\([^)]*\))?$"),
    )
    return next(
        (label for label, pattern in patterns if re.fullmatch(pattern, plain)), None
    )


def wilson(successes: int, total: int) -> tuple[float, float]:
    if total == 0:
        return 0.0, 1.0
    z = 1.959963984540054
    proportion = successes / total
    denominator = 1 + z * z / total
    center = (proportion + z * z / (2 * total)) / denominator
    margin = (
        z
        * math.sqrt(proportion * (1 - proportion) / total + z * z / (4 * total * total))
        / denominator
    )
    return center - margin, center + margin


def reference_prediction(score: object) -> str:
    if isinstance(score, bool) or not isinstance(score, int) or not 0 <= score <= 100:
        raise ValueError("reference fit_score must be an integer from 0 through 100")
    return "Pursue" if score >= 70 else "Maybe" if score >= 40 else "No"


def jev_prediction(answer: object, confidence: object, floor: float) -> str:
    if not isinstance(answer, str):
        raise TypeError("Jev answer must be a label")
    labels = {label.casefold(): label for label in LABELS}
    if answer.casefold() not in labels:
        raise ValueError("Jev answer is outside the three-label contract")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        raise TypeError("Jev confidence must be numeric")
    confidence = float(confidence)
    if not math.isfinite(confidence) or not 0 <= confidence <= 1:
        raise ValueError("Jev confidence must be between zero and one")
    return labels[answer.casefold()] if confidence >= floor else "abstain"


def _metrics(gold: Sequence[str], predicted: Sequence[str]) -> dict[str, Any]:
    if len(gold) != len(predicted):
        raise ValueError("gold and prediction lengths differ")
    if any(label not in LABELS for label in gold):
        raise ValueError("gold contains an unsupported label")
    allowed_predictions = set(LABELS) | {"abstain"}
    if any(label not in allowed_predictions for label in predicted):
        raise ValueError("predictions contain an unsupported label")
    exact = sum(truth == guess for truth, guess in zip(gold, predicted, strict=True))
    pursue_n = sum(truth == "Pursue" for truth in gold)
    pursue_hits = sum(
        truth == "Pursue" and guess == "Pursue"
        for truth, guess in zip(gold, predicted, strict=True)
    )
    no_n = sum(truth == "No" for truth in gold)
    false_fires = sum(
        truth == "No" and guess == "Pursue"
        for truth, guess in zip(gold, predicted, strict=True)
    )
    non_no_n = len(gold) - no_n
    false_rejections = sum(
        truth != "No" and guess == "No"
        for truth, guess in zip(gold, predicted, strict=True)
    )
    matrix = {truth: {guess: 0 for guess in (*LABELS, "abstain")} for truth in LABELS}
    for truth, guess in zip(gold, predicted, strict=True):
        matrix[truth][guess] += 1
    return {
        "n": len(gold),
        "exact_hits": exact,
        "exact_accuracy": exact / len(gold) if gold else 0.0,
        "exact_accuracy_wilson_95": wilson(exact, len(gold)),
        "pursue_n": pursue_n,
        "pursue_hits": pursue_hits,
        "pursue_recall": pursue_hits / pursue_n if pursue_n else 0.0,
        "pursue_recall_wilson_95": wilson(pursue_hits, pursue_n),
        "misses": pursue_n - pursue_hits,
        "no_n": no_n,
        "false_fires": false_fires,
        "false_fire_rate": false_fires / no_n if no_n else 0.0,
        "false_fire_wilson_95": wilson(false_fires, no_n),
        "non_no_n": non_no_n,
        "false_rejections": false_rejections,
        "false_rejection_rate": false_rejections / non_no_n if non_no_n else 0.0,
        "false_rejection_wilson_95": wilson(false_rejections, non_no_n),
        "predicted_no": sum(guess == "No" for guess in predicted),
        "abstentions": sum(guess == "abstain" for guess in predicted),
        "confusion": matrix,
    }


def _percentile(values: Sequence[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(fraction * len(ordered)) - 1)
    return ordered[index]


def _cost_latency(rows: Sequence[Mapping[str, Any]], run: int) -> dict[str, Any]:
    jev_rows = [next(item for item in row["jev"] if item["run"] == run) for row in rows]
    jev_costs = [float(item["cost_usd"]) for item in jev_rows]
    jev_latencies = [float(item["latency_seconds"]) for item in jev_rows]
    reference_latencies = [float(row["reference"]["latency_seconds"]) for row in rows]
    reference_costs = {row["reference"].get("cost_per_row_usd") for row in rows}
    if reference_costs != {None}:
        raise ValueError(
            "subscription reference cost must remain explicitly unobservable"
        )
    return {
        "jev": {
            "calls": len(jev_rows),
            "cost_usd": sum(jev_costs),
            "cost_per_row_usd": statistics.mean(jev_costs) if jev_costs else None,
            "latency_mean_seconds": statistics.mean(jev_latencies)
            if jev_latencies
            else None,
            "latency_p50_seconds": _percentile(jev_latencies, 0.50),
            "latency_p95_seconds": _percentile(jev_latencies, 0.95),
        },
        "reference": {
            "calls": len(rows),
            "cost_per_row_usd": None,
            "cost_note": "not observable (subscription runner)",
            "latency_mean_seconds": statistics.mean(reference_latencies)
            if reference_latencies
            else None,
            "latency_p50_seconds": _percentile(reference_latencies, 0.50),
            "latency_p95_seconds": _percentile(reference_latencies, 0.95),
        },
    }


def _predictions(
    rows: Sequence[Mapping[str, Any]], run: int, floor: float
) -> tuple[list[str], list[str], list[str]]:
    gold, reference, jev = [], [], []
    for row in rows:
        gold.append(row["gold"]["label"])
        reference.append(reference_prediction(row["reference"]["fit_score"]))
        observation = next(item for item in row["jev"] if item["run"] == run)
        jev.append(
            jev_prediction(observation["answer"], observation["confidence"], floor)
        )
    return gold, reference, jev


def _verdict(
    part_metrics: Mapping[str, Mapping[str, Any]], pooled: Mapping[str, Any]
) -> dict[str, Any]:
    margin = (
        pooled["jev"]["exact_accuracy_wilson_95"][0]
        - pooled["reference"]["exact_accuracy"]
    )
    replace_guards = all(
        item["jev"]["exact_accuracy"] >= item["reference"]["exact_accuracy"]
        and item["jev"]["misses"] <= item["reference"]["misses"]
        and item["jev"]["false_fires"] <= item["reference"]["false_fires"]
        for item in part_metrics.values()
    )
    if margin >= 0 and replace_guards:
        return {
            "label": "REPLACE",
            "deciding_metric": "replace_accuracy_margin",
            "value": margin,
        }
    false_rejection_upper = pooled["jev"]["false_rejection_wilson_95"][1]
    prefilter_guards = pooled["jev"]["predicted_no"] >= 3 and all(
        item["jev"]["false_rejections"] == 0 for item in part_metrics.values()
    )
    if prefilter_guards and false_rejection_upper <= 0.20:
        return {
            "label": "PREFILTER-ONLY",
            "deciding_metric": "false_rejection_wilson_upper",
            "value": false_rejection_upper,
        }
    if pooled["jev"]["predicted_no"] < 3:
        metric, value = "confident_no_count", pooled["jev"]["predicted_no"]
    elif not all(
        item["jev"]["false_rejections"] == 0 for item in part_metrics.values()
    ):
        metric, value = "false_rejections", pooled["jev"]["false_rejections"]
    else:
        metric, value = "false_rejection_wilson_upper", false_rejection_upper
    return {"label": "NO-GO", "deciding_metric": metric, "value": value}


def summarize_manifest(manifest: Mapping[str, Any]) -> dict[str, Any]:
    if manifest.get("schema_version") != 1 or not isinstance(
        manifest.get("rows"), list
    ):
        raise ValueError("unsupported manifest")
    rows = manifest["rows"]
    if not rows:
        raise ValueError("manifest contains no rows")
    locators: set[str] = set()
    run_sets: list[set[int]] = []
    for row in rows:
        locator = row.get("locator")
        if not isinstance(locator, str) or not locator or locator in locators:
            raise ValueError("manifest locators must be unique nonblank strings")
        locators.add(locator)
        expected = hashlib.sha256(
            canonical_json(row["frozen_input"]).encode()
        ).hexdigest()
        if row.get("input_sha256") != expected:
            raise ValueError(f"frozen input sha256 mismatch for {locator}")
        if parse_verdict(row["gold"]["verbatim"]) != row["gold"].get("label"):
            raise ValueError(f"gold parse mismatch for {locator}")
        runs = [item.get("run") for item in row.get("jev", [])]
        if any(type(run) is not int or run < 1 for run in runs) or len(runs) != len(
            set(runs)
        ):
            raise ValueError(f"invalid Jev runs for {locator}")
        run_sets.append(set(runs))
    if not run_sets[0] or any(runs != run_sets[0] for runs in run_sets[1:]):
        raise ValueError("every posting must have the same complete Jev run set")

    output_runs = []
    for run in sorted(run_sets[0]):
        parts: dict[str, Any] = {}
        for part in sorted({row["part"] for row in rows}):
            subset = [row for row in rows if row["part"] == part]
            gold, reference, jev = _predictions(subset, run, FIXED_FLOOR)
            parts[str(part)] = {
                "reference": _metrics(gold, reference),
                "jev": _metrics(gold, jev),
            }
        gold, reference, jev = _predictions(rows, run, FIXED_FLOOR)
        pooled = {"reference": _metrics(gold, reference), "jev": _metrics(gold, jev)}
        curve = []
        for floor in FLOORS:
            floor_parts = {}
            for part in sorted({row["part"] for row in rows}):
                subset = [row for row in rows if row["part"] == part]
                part_gold, _, part_jev = _predictions(subset, run, floor)
                floor_parts[str(part)] = _metrics(part_gold, part_jev)
            floor_gold, _, floor_jev = _predictions(rows, run, floor)
            curve.append(
                {
                    "floor": floor,
                    "parts": floor_parts,
                    "pooled": _metrics(floor_gold, floor_jev),
                }
            )
        output_runs.append(
            {
                "run": run,
                "parts": parts,
                "pooled": pooled,
                "threshold_curve": curve,
                "cost_latency": _cost_latency(rows, run),
                "verdict": _verdict(parts, pooled),
            }
        )
    return {"schema_version": 1, "row_count": len(rows), "runs": output_runs}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args(argv)
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    print(
        json.dumps(
            summarize_manifest(manifest), ensure_ascii=False, indent=2, sort_keys=True
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
