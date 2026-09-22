"""Forward-test label parsing, decision policy, and Markdown reporting."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from scraper.forward_scoring_harness import (
    jev_prediction,
    summarize_manifest,
    wilson,
)

FLOORS = tuple(value / 100 for value in range(50, 100, 5))


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


def _accuracy(rows: Sequence[Mapping[str, Any]], run: int, floor: float) -> float:
    hits = 0
    for row in rows:
        observation = next(item for item in row["jev"] if item["run"] == run)
        predicted = jev_prediction(
            observation["answer"], observation["confidence"], floor
        )
        hits += predicted == row["gold"]["label"]
    return hits / len(rows)


def _threshold_curve(
    rows: Sequence[Mapping[str, Any]], run: int
) -> list[dict[str, Any]]:
    curve = []
    for floor in FLOORS:
        parts = {
            str(part): _accuracy(
                [row for row in rows if row["part"] == part], run, floor
            )
            for part in (1, 2, 3)
        }
        non_radar = _accuracy(
            [row for row in rows if row["part"] in {2, 3}], run, floor
        )
        curve.append(
            {
                "floor": floor,
                "parts": parts,
                "non_radar": non_radar,
                "pooled": _accuracy(rows, run, floor),
            }
        )
    return curve


def _false_rejection_intervals(metric: Mapping[str, Any]) -> dict[str, Any]:
    errors = metric["false_rejections"]
    eligible = metric["non_no_n"]
    prefiltered = metric["predicted_no"]
    return {
        "eligible_positive": {
            "errors": errors,
            "denominator": eligible,
            "wilson_95": wilson(errors, eligible),
        },
        "actual_prefiltered": {
            "errors": errors,
            "denominator": prefiltered,
            "wilson_95": wilson(errors, prefiltered),
        },
    }


def _verdict(parts: Mapping[str, Any], pooled: Mapping[str, Any]) -> dict[str, Any]:
    margin = (
        pooled["jev"]["exact_accuracy_wilson_95"][0]
        - pooled["reference"]["exact_accuracy"]
    )
    replace_guards = all(
        item["jev"]["exact_accuracy"] >= item["reference"]["exact_accuracy"]
        and item["jev"]["misses"] <= item["reference"]["misses"]
        and item["jev"]["false_fires"] <= item["reference"]["false_fires"]
        for item in parts.values()
    )
    if margin >= 0 and replace_guards:
        return {
            "label": "REPLACE",
            "metric": "replace_accuracy_margin",
            "value": margin,
        }
    upper = pooled["jev"]["false_rejection_wilson_95"][1]
    prefilter_guards = pooled["jev"]["predicted_no"] >= 4 and all(
        item["jev"]["false_rejections"] == 0 for item in parts.values()
    )
    if prefilter_guards and upper <= 0.20:
        return {
            "label": "PREFILTER-ONLY",
            "metric": "eligible_positive_wilson_upper",
            "value": upper,
        }
    if pooled["jev"]["predicted_no"] < 4:
        metric, value = "confident_no_count", pooled["jev"]["predicted_no"]
    elif not all(item["jev"]["false_rejections"] == 0 for item in parts.values()):
        metric, value = "false_rejections", pooled["jev"]["false_rejections"]
    else:
        metric, value = "eligible_positive_wilson_upper", upper
    return {"label": "NO-GO", "metric": metric, "value": value}


def summarize_forward(manifest: Mapping[str, Any]) -> dict[str, Any]:
    rows = manifest.get("rows")
    if isinstance(rows, list):
        for row in rows:
            gold = row.get("gold") if isinstance(row, Mapping) else None
            verbatim = gold.get("verbatim") if isinstance(gold, Mapping) else None
            if isinstance(verbatim, str) and parse_verdict(verbatim) != gold.get(
                "label"
            ):
                raise ValueError("verbatim verdict does not match declared gold label")
    summary = summarize_manifest(manifest)
    rows = manifest["rows"]
    for run in summary["runs"]:
        run["threshold_curve"] = _threshold_curve(rows, run["run"])
        run["verdict"] = _verdict(run["parts"], run["pooled"])
        run["false_rejection_intervals"] = _false_rejection_intervals(
            run["pooled"]["jev"]
        )
    return summary


def _matrix(lines: list[str], label: str, metric: Mapping[str, Any]) -> None:
    lines += [
        "",
        f"**{label} confusion**",
        "",
        "| Gold | Pursue | Maybe | No | Abstain |",
        "|---|---:|---:|---:|---:|",
    ]
    for gold, values in metric["confusion"].items():
        lines.append(
            f"| {gold} | {values['Pursue']} | {values['Maybe']} | "
            f"{values['No']} | {values['abstain']} |"
        )


def _arm_section(
    lines: list[str], heading: str, arms: Mapping[str, Mapping[str, Any]]
) -> None:
    lines += [
        "",
        f"### {heading}",
        "",
        "| Arm | Exact accuracy (95% Wilson) | Pursue recall | Misses | False fires |",
        "|---|---:|---:|---:|---:|",
    ]
    for arm in ("reference", "jev"):
        metric = arms[arm]
        low, high = metric["exact_accuracy_wilson_95"]
        lines.append(
            f"| {arm} | {metric['exact_hits']}/{metric['n']} = {metric['exact_accuracy']:.3f} "
            f"({low:.3f}–{high:.3f}) | {metric['pursue_recall']:.3f} | "
            f"{metric['misses']} | {metric['false_fires']} |"
        )
    for arm in ("reference", "jev"):
        _matrix(lines, arm, arms[arm])


def render_report(manifest: Mapping[str, Any]) -> str:
    summary = summarize_forward(manifest)
    executed = summary["row_count"]
    planned = len(manifest["expected_locators"])
    clear_no_count = sum(row["gold"]["label"] == "No" for row in manifest["rows"])
    lines = [
        f"# Forward scoring — {executed} executed labels ({planned} planned)",
        "",
        "## Human-label parse table",
        "",
        "| Part | Posting | Verbatim verdict | Parsed label |",
        "|---:|---|---|---|",
    ]
    for row in manifest["rows"]:
        posting = row["frozen_input"]["hosted_payload"]["public_posting"]
        gold = row["gold"]
        values = (
            row["part"],
            f"{posting['company']} — {posting['title']}",
            gold["verbatim"],
            parse_verdict(gold["verbatim"]),
        )
        lines.append(
            "| " + " | ".join(str(value).replace("|", "\\|") for value in values) + " |"
        )
    lines += [
        "",
        "Excluded rows: "
        + (", ".join(item["locator"] for item in manifest["dropped"]) or "none"),
    ]
    for run in summary["runs"]:
        verdict = run["verdict"]
        lines += [
            "",
            f"## Run {run['run']}",
            "",
            f"VERDICT: **{verdict['label']}** — `{verdict['metric']}` = **{verdict['value']:.4f}**.",
        ]
        for part in ("1", "2", "3"):
            _arm_section(lines, f"Part {part}", run["parts"][part])
        _arm_section(
            lines,
            "Non-radar subtotal (Parts 2+3)",
            run["subtotals"]["non_radar"],
        )
        _arm_section(lines, "Pooled", run["pooled"])
        lines += [
            "",
            "### Accuracy vs Jev confidence floor",
            "",
            "| Floor | Part 1 | Part 2 | Part 3 | Non-radar | Pooled |",
            "|---:|---:|---:|---:|---:|---:|",
        ]
        for point in run["threshold_curve"]:
            lines.append(
                f"| {point['floor']:.2f} | {point['parts']['1']:.3f} | "
                f"{point['parts']['2']:.3f} | {point['parts']['3']:.3f} | "
                f"{point['non_radar']:.3f} | {point['pooled']:.3f} |"
            )
        intervals = run["false_rejection_intervals"]
        lines += [
            "",
            "### PREFILTER uncertainty at 0.70",
            "",
            "| Denominator | False rejections / n | Wilson 95% | Acceptance role |",
            "|---|---:|---:|---|",
        ]
        for name, note in (
            ("eligible_positive", "precommitted bar"),
            ("actual_prefiltered", "supplementary only"),
        ):
            item = intervals[name]
            low, high = item["wilson_95"]
            lines.append(
                f"| {name.replace('_', ' ')} | {item['errors']}/{item['denominator']} | {low:.3f}–{high:.3f} | {note} |"
            )
        cost = run["cost_latency"]
        lines += [
            "",
            "### Cost and latency",
            "",
            f"- Jev: {cost['jev']['calls']} calls, ${cost['jev']['cost_usd']:.8f} total, ${cost['jev']['cost_per_row_usd']:.8f}/row; mean {cost['jev']['latency_mean_seconds']:.3f}s, p50 {cost['jev']['latency_p50_seconds']:.3f}s, p95 {cost['jev']['latency_p95_seconds']:.3f}s.",
            f"- Reference: {cost['reference']['calls']} calls; cost/row **not observable (subscription runner)**; mean {cost['reference']['latency_mean_seconds']:.3f}s, p50 {cost['reference']['latency_p50_seconds']:.3f}s, p95 {cost['reference']['latency_p95_seconds']:.3f}s.",
        ]
    execution = manifest.get("execution", {})
    lines += [
        "",
        "## Runtime and limitations",
        "",
        f"- Reference runtime: `{execution.get('codex_cli_version', 'not recorded')}`; production pin: `{execution.get('production_codex_pin', 'not recorded')}`. The installed runtime is an approved experiment-only deviation; the production pin was not changed.",
        "- Hosted requests contained the professional profile projection and public posting only; application history and truth labels were excluded.",
        "- Production decision bands: >=70 Pursue, 40–69 Maybe, <40 No. Fixed Jev decision floor: 0.70.",
        f"- Only {clear_no_count} executed labels are clear No's, so the reject class remains thin despite the stratified Part 3 sample.",
    ]
    if len(summary["runs"]) > 1:
        values = [run["pooled"]["jev"]["exact_accuracy"] for run in summary["runs"]]
        lines += [
            f"- Between-run pooled Jev exact-accuracy spread: {min(values):.3f}–{max(values):.3f}; runs were not pooled."
        ]
    return "\n".join(lines) + "\n"
