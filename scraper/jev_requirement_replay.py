#!/usr/bin/env python3
"""Read-only E5 replay of repository-labelled requirement decisions through Jev."""

from __future__ import annotations

import argparse
import importlib
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal, Sequence

from scraper import harvest, jev_client

HERE = Path(__file__).resolve().parent
FIXTURE = HERE / "fixtures" / "job-radar-rescore-2026-08-11.json"
PROFILE = HERE.parent / "profile.example.yaml"
HARD = "hard_requirement"
WAIVED = "waived_or_no_match"
PRIOR_SPEND_USD = 0.005377
Assertion = Literal["exact", "subset"]


@dataclass(frozen=True)
class Occurrence:
    label: str
    mention: str
    start: int
    end: int


@dataclass(frozen=True)
class Case:
    id: str
    source: str
    title: str
    posting_text: str
    occurrences: tuple[Occurrence, ...]
    current_negative_hits: tuple[str, ...]
    expected_negative_hits: tuple[str, ...]
    assertion: Assertion

    def passes(self, predicted: set[str]) -> bool:
        expected = set(self.expected_negative_hits)
        return predicted == expected if self.assertion == "exact" else expected <= predicted


@dataclass(frozen=True)
class Decision:
    run: int
    case: Case
    occurrence: Occurrence
    answer: str
    confidence: float
    model: str
    acted: bool


@dataclass(frozen=True)
class CurveRow:
    floor: float
    agreement: int
    considered: int
    abstentions: int
    false_waives: int
    false_blocks: int


@dataclass(frozen=True)
class ReplayResult:
    cases: tuple[Case, ...]
    decisions: tuple[Decision, ...]
    curve: tuple[CurveRow, ...]
    planned_calls: int
    actual_calls: int
    planned_cost_usd: float
    actual_cost_usd: float
    wall_seconds: float
    models: set[str]
    input_tokens: int
    output_tokens: int
    runs: int


def _param_rows(name: str) -> list[object]:
    module = importlib.import_module("scraper.test_harvest")
    marks = [mark for mark in getattr(module, name).pytestmark if mark.name == "parametrize"]
    if len(marks) != 1:
        raise ValueError(f"expected one parametrize mark on {name}")
    return list(marks[0].args[1])


def _year_label(minimum: int) -> str | None:
    for threshold, label, _weight in harvest.YEAR_BANDS:
        if minimum >= threshold:
            return label
    return None


def _candidate_occurrences(title: str, text: str) -> tuple[Occurrence, ...]:
    full_text = f"{title} {text}".strip()
    found: list[Occurrence] = []
    for label, pattern, _weight, scope in harvest.NEGATIVE_RULES:
        haystack = title if scope == harvest.TITLE_ONLY else full_text
        found.extend(Occurrence(label, match.group(0), match.start(), match.end()) for match in pattern.finditer(haystack))
    for match in harvest.YEARS_REQUIREMENT_PATTERN.finditer(full_text):
        label = _year_label(int(match.group("minimum")))
        if label:
            found.append(Occurrence(label, match.group(0), match.start(), match.end()))
    for technology, (pattern, _weight) in harvest.INFRA_WALL_PATTERNS.items():
        found.extend(Occurrence(f"infra:{technology}", match.group(0), match.start(), match.end()) for match in pattern.finditer(full_text))
    found.extend(Occurrence("python-primary", match.group(0), match.start(), match.end()) for match in re.finditer(r"\bpython\b", full_text, re.I))
    return tuple(dict.fromkeys(found))


def _case(case_id: str, source: str, title: str, text: str, expected: set[str], assertion: Assertion) -> Case:
    posting = {"title": title, "raw_text": title, "jd_text": text, "jd_fetched": bool(text)}
    current = harvest.score_posting(posting)["negative_hits"]
    return Case(case_id, source, title, text or title, _candidate_occurrences(title, text),
                tuple(str(value) for value in current), tuple(sorted(expected)), assertion)


def load_cases() -> list[Case]:
    cases: list[Case] = []
    source = "test_harvest.py"
    for index, row in enumerate(_param_rows("test_score_posting_rules"), 1):
        text, _positive, _senior, _keywords, expected = row
        cases.append(_case(f"score-{index}", source, text, "", set(expected), "exact"))
    for index, row in enumerate(_param_rows("test_live_triage_negative_rules"), 1):
        requirement, label, _weight = row
        cases.append(_case(f"triage-{index}", source, requirement, "", {label}, "exact"))
    for index, row in enumerate(_param_rows("test_live_2026_08_10_role_controls"), 1):
        title, text, _positive, label = row
        cases.append(_case(f"role-{index}", source, title, text, {label} if label else set(), "subset"))
    for index, requirement in enumerate(_param_rows("test_high_year_requirements_match_common_jd_phrasings"), 1):
        cases.append(_case(f"years-{index}", source, "Software Engineer", requirement, {"8-9+ years"}, "exact"))
    for index, row in enumerate(_param_rows("test_polyglot_alternative_list_does_not_trigger_stack_negative"), 1):
        _job_id, requirement, _positive = row
        cases.append(_case(f"polyglot-{index}", source, "Backend Software Engineer", requirement, set(), "subset"))
    for index, row in enumerate(_param_rows("test_required_infra_and_python_primary_are_strong_negative_walls"), 1):
        title, requirement, expected = row
        cases.append(_case(f"walls-{index}", source, title, requirement, set(expected), "subset"))
    profile = harvest.load_profile_contract(PROFILE)
    for row in json.loads(FIXTURE.read_text(encoding="utf-8")):
        scored = harvest.score_posting(row, profile["fit_terms"])
        cases.append(Case(f"fixture-{row['id']}", FIXTURE.name, row["title"], row["jd_text"],
                          _candidate_occurrences(row["title"], row["jd_text"]), tuple(scored["negative_hits"]),
                          tuple(row["expected_negative_hits"]), "exact"))
    return cases


def public_posting_sanitizer(state: object) -> object:
    if not isinstance(state, dict) or set(state) != {"title", "posting_text", "occurrence"}:
        raise ValueError("E5 accepts only title, public posting_text, and occurrence")
    if not all(isinstance(state[key], str) for key in state):
        raise ValueError("E5 posting fields must be strings")
    return state


QUESTION = jev_client.Question(
    id="requirement_verdict", type="choice",
    instructions=("Evaluate only `occurrence` in its posting context. Does this occurrence establish a hard "
                  "requirement for the role, rather than an example, preference, optional skill, or alternative?"),
    criteria={HARD: "This occurrence is mandatory or clearly required.",
              WAIVED: "This occurrence is not required, is optional, or is only an example/alternative."},
    fallback=WAIVED,
)


def _predicted(rows: Sequence[Decision], floor: float = 0.0) -> set[str]:
    return {row.occurrence.label for row in rows if row.confidence >= floor and row.answer == HARD}


def _curve(cases: Sequence[Case], decisions: Sequence[Decision], runs: int,
           run_ids: Sequence[int] | None = None) -> tuple[CurveRow, ...]:
    selected_runs = tuple(run_ids or range(1, runs + 1))
    result = []
    for integer_floor in range(50, 100, 5):
        floor, agreement = integer_floor / 100, 0
        considered = false_waives = false_blocks = 0
        for run in selected_runs:
            for case in cases:
                rows = [row for row in decisions if row.run == run and row.case.id == case.id]
                if any(row.confidence < floor for row in rows):
                    continue
                considered += 1
                predicted, expected = _predicted(rows, floor), set(case.expected_negative_hits)
                agreement += case.passes(predicted)
                false_waives += bool(expected - predicted)
                false_blocks += bool(case.assertion == "exact" and predicted - expected)
        result.append(CurveRow(floor, agreement, considered, len(cases) * len(selected_runs) - considered,
                               false_waives, false_blocks))
    return tuple(result)


def run_replay(cases: Sequence[Case], *, runs: int, sanitizer: Callable[[object], object],
               transport: jev_client.Transport | None = None, log_path: Path = jev_client.DEFAULT_LOG,
               usage_path: Path = jev_client.DEFAULT_USAGE) -> ReplayResult:
    planned_calls = sum(len(case.occurrences) for case in cases) * runs
    planned_cost = planned_calls * jev_client.maximum_call_cost()
    decisions: list[Decision] = []
    actual_calls = input_tokens = output_tokens = 0
    cost = 0.0
    started = time.monotonic()
    for run in range(1, runs + 1):
        for case in cases:
            for occurrence in case.occurrences:
                state = {"title": case.title, "posting_text": case.posting_text, "occurrence": occurrence.mention}
                answer = jev_client.jev(state, [QUESTION], site="jrc-e5", sanitizer=sanitizer, transport=transport,
                                        log_path=log_path, usage_path=usage_path)[0]
                actual_calls += int(answer.called)
                cost += answer.cost_usd
                input_tokens += answer.input_tokens
                output_tokens += answer.output_tokens
                decisions.append(Decision(run, case, occurrence, str(answer.answer), answer.confidence,
                                          answer.model, answer.acted))
    if any(row.acted for row in decisions):
        raise RuntimeError("E5 emitted an acted=true decision")
    return ReplayResult(tuple(cases), tuple(decisions), _curve(cases, decisions, runs), planned_calls, actual_calls,
                        planned_cost, cost, time.monotonic() - started, {row.model for row in decisions},
                        input_tokens, output_tokens, runs)


def _run_cells(result: ReplayResult, case: Case) -> list[str]:
    cells = []
    for run in range(1, result.runs + 1):
        rows = [row for row in result.decisions if row.run == run and row.case.id == case.id]
        predicted = _predicted(rows)
        cells.append(f"{', '.join(sorted(predicted)) or '—'} ({'pass' if case.passes(predicted) else 'fail'})")
    return cells


def render_report(result: ReplayResult) -> str:
    lines = ["# E5 — Job Radar requirement-vs-example replay", "",
             "The earlier E5 numbers are withdrawn: that harness made one binary decision per row, so one hard candidate could hide missed asserted labels. This corrected shadow-only run makes one decision per candidate occurrence and reconstructs each row's predicted hit set.", "",
             "## Run receipt", "", f"- Planned / actual calls: **{result.planned_calls} / {result.actual_calls}**",
             f"- Worst-case reserved ceiling / actual cost: **${result.planned_cost_usd:.6f} / ${result.actual_cost_usd:.6f}**",
             f"- Tracked cumulative lane spend (including $0.005377 prior): **${PRIOR_SPEND_USD + result.actual_cost_usd:.6f}**",
             f"- Lane upper bound including one unmetered diagnostic probe: **<${PRIOR_SPEND_USD + result.actual_cost_usd + jev_client.maximum_call_cost():.6f}**, below the $1 cap",
             f"- Wall time: **{result.wall_seconds:.2f}s**", f"- Model/version: **{', '.join(sorted(result.models))}**",
             f"- Tokens: **{result.input_tokens} input / {result.output_tokens} output**", "", "## Accuracy vs confidence threshold", "",
             "A row abstains if any of its candidate occurrences is below the floor.", "",
             "| Floor | Assertion-pass | Abstentions | False waives | False blocks |", "|---:|---:|---:|---:|---:|"]
    for row in result.curve:
        lines.append(f"| {row.floor:.2f} | {row.agreement}/{row.considered} | {row.abstentions} | {row.false_waives} | {row.false_blocks} |")
    lines += ["", "## Per-run variance", "", "Each cell is assertion-pass/considered; abstentions; false-waives; false-blocks.", "",
              "| Floor | Run 1 | Run 2 | Run 3 |", "|---:|---|---|---|"]
    per_run = {run: _curve(result.cases, result.decisions, result.runs, [run])
               for run in range(1, result.runs + 1)}
    for index, floor in enumerate(value / 100 for value in range(50, 100, 5)):
        cells = []
        for run in range(1, result.runs + 1):
            row = per_run[run][index]
            cells.append(f"{row.agreement}/{row.considered}; {row.abstentions}; {row.false_waives}; {row.false_blocks}")
        lines.append(f"| {floor:.2f} | " + " | ".join(cells) + " |")
    lines += ["", "## Pass bar by expected_negative_hits row", "",
              "Exact rows require set equality; subset rows preserve the source test's inclusion-only assertion.", "",
              "| Row | Semantics | Expected | Run 1 | Run 2 | Run 3 | All pass |", "|---|---|---|---|---|---|---|"]
    for case in result.cases:
        cells = _run_cells(result, case)
        lines.append(f"| {case.id} | {case.assertion} | {', '.join(case.expected_negative_hits) or '—'} | " + " | ".join(cells) + f" | {'yes' if all('pass)' in cell for cell in cells) else 'no'} |")
    all_pass = all(all("pass)" in cell for cell in _run_cells(result, case)) for case in result.cases)
    lines += ["", "## Replacement read", "", f"- Reproduces every row in every run: **{'YES' if all_pass else 'NO'}**.",
              "- If it passed, it could replace the roughly 120-line context/waiver regex tower around `scraper/harvest.py:641` and `:679`; this experiment does not switch that call site.",
              f"- Honest read: **{'close on this frozen set, but still shadow-only' if all_pass else 'not close enough to replace the deterministic scorer'}**.", ""]
    return "\n".join(lines)


def rescore_table_via_existing_script() -> str:
    completed = subprocess.run([sys.executable, str(HERE / "rescore_fixture.py"), "--fixture", str(FIXTURE), "--profile", str(PROFILE)],
                               capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        raise RuntimeError("existing rescore fixture script failed")
    return completed.stdout.strip()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", action="store_true")
    parser.add_argument("--real", action="store_true")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--max-calls", type=int, default=1000)
    parser.add_argument("--max-usd", type=float, default=0.994623)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--decision-log", type=Path, default=jev_client.DEFAULT_LOG)
    parser.add_argument("--usage-log", type=Path, default=jev_client.DEFAULT_USAGE)
    args = parser.parse_args(argv)
    if jev_client._site_mode("jrc-e5") != "shadow":
        print("ABORT: E5 requires effective mode shadow")
        return 2
    cases = load_cases()
    calls = sum(len(case.occurrences) for case in cases) * args.runs
    ceiling = calls * jev_client.maximum_call_cost()
    estimate = sum(jev_client.estimate_cost({"title": case.title, "posting_text": case.posting_text,
                                              "occurrence": occurrence.mention}, QUESTION)
                   for case in cases for occurrence in case.occurrences) * args.runs
    print(f"planned_calls={calls} estimated_cost_usd={estimate:.6f} worst_case_reservations_usd={ceiling:.6f} remaining_lane_cap_usd={args.max_usd:.6f}")
    if calls > args.max_calls or estimate > args.max_usd:
        print("ABORT: replay exceeds printed call plan or remaining lane cap")
        return 2
    if args.plan:
        return 0
    if not args.real:
        parser.error("choose --plan or --real")
    os.environ["JEV_DAILY_USD_CAP"] = str(args.max_usd)
    result = run_replay(cases, runs=args.runs, sanitizer=public_posting_sanitizer,
                        log_path=args.decision_log, usage_path=args.usage_log)
    if result.actual_calls != calls or result.actual_cost_usd > args.max_usd or any(row.acted for row in result.decisions):
        raise RuntimeError("actual replay violated its printed plan, cap, or shadow invariant")
    report = render_report(result) + "\n## Existing rescore_fixture.py before/after table\n\n" + rescore_table_via_existing_script() + "\n"
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(report, encoding="utf-8")
    else:
        print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
