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
from typing import Callable, Sequence

from scraper import harvest
from scraper import jev_client

HERE = Path(__file__).resolve().parent
FIXTURE = HERE / "fixtures" / "job-radar-rescore-2026-08-11.json"
PROFILE = HERE.parent / "profile.example.yaml"
HARD = "hard_requirement"
WAIVED = "waived_or_no_match"


@dataclass(frozen=True)
class Case:
    id: str
    source: str
    state: dict[str, object]
    current_negative_hits: tuple[str, ...]
    expected_negative_hits: tuple[str, ...]

    @property
    def current_regex_verdict(self) -> str:
        return HARD if self.current_negative_hits else WAIVED

    @property
    def repo_label(self) -> str:
        return HARD if self.expected_negative_hits else WAIVED


@dataclass(frozen=True)
class Decision:
    run: int
    case: Case
    answer: str
    confidence: float
    model: str


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
    decisions: tuple[Decision, ...]
    curve: tuple[CurveRow, ...]
    run_summaries: tuple[tuple[int, int, int], ...]
    planned_calls: int
    actual_calls: int
    planned_cost_usd: float
    actual_cost_usd: float
    wall_seconds: float
    models: set[str]
    input_tokens: int
    output_tokens: int


def _param_rows(name: str) -> list[object]:
    module = importlib.import_module("scraper.test_harvest")
    marks = [
        mark for mark in getattr(module, name).pytestmark if mark.name == "parametrize"
    ]
    if len(marks) != 1:
        raise ValueError(f"expected one parametrize mark on {name}")
    return list(marks[0].args[1])


def _case(case_id: str, source: str, title: str, text: str, expected: set[str]) -> Case:
    posting = {
        "title": title,
        "raw_text": title,
        "jd_text": text,
        "jd_fetched": bool(text),
    }
    current = harvest.score_posting(posting)["negative_hits"]
    return Case(
        case_id,
        source,
        {
            "title": title,
            "posting_text": text or title,
            "candidate_mentions": _candidate_mentions(title, text),
        },
        tuple(str(value) for value in current),
        tuple(sorted(expected)),
    )


def _candidate_mentions(title: str, text: str) -> list[str]:
    full_text = f"{title} {text}".strip()
    mentions: list[str] = []
    for _label, pattern, _weight, scope in harvest.NEGATIVE_RULES:
        haystack = title if scope == harvest.TITLE_ONLY else full_text
        mentions.extend(match.group(0) for match in pattern.finditer(haystack))
    mentions.extend(
        match.group(0)
        for match in harvest.YEARS_REQUIREMENT_PATTERN.finditer(full_text)
        if int(match.group("minimum")) >= 5
    )
    for pattern, _weight in harvest.INFRA_WALL_PATTERNS.values():
        mentions.extend(match.group(0) for match in pattern.finditer(full_text))
    mentions.extend(
        match.group(0) for match in re.finditer(r"\bpython\b", full_text, re.I)
    )
    return list(dict.fromkeys(mention.casefold() for mention in mentions))


def load_cases() -> list[Case]:
    cases: list[Case] = []
    source = "test_harvest.py"
    for index, row in enumerate(_param_rows("test_score_posting_rules"), 1):
        text, _positive, _senior, _keywords, expected = row
        cases.append(_case(f"score-{index}", source, text, "", set(expected)))
    for index, row in enumerate(_param_rows("test_live_triage_negative_rules"), 1):
        requirement, label, _weight = row
        cases.append(_case(f"triage-{index}", source, requirement, "", {label}))
    for index, row in enumerate(_param_rows("test_live_2026_08_10_role_controls"), 1):
        title, text, _positive, label = row
        cases.append(
            _case(f"role-{index}", source, title, text, {label} if label else set())
        )
    for index, requirement in enumerate(
        _param_rows("test_high_year_requirements_match_common_jd_phrasings"), 1
    ):
        cases.append(
            _case(
                f"years-{index}",
                source,
                "Software Engineer",
                requirement,
                {"8-9+ years"},
            )
        )
    for index, row in enumerate(
        _param_rows("test_polyglot_alternative_list_does_not_trigger_stack_negative"), 1
    ):
        _job_id, requirement, _positive = row
        cases.append(
            _case(
                f"polyglot-{index}",
                source,
                "Backend Software Engineer",
                requirement,
                set(),
            )
        )
    for index, row in enumerate(
        _param_rows("test_required_infra_and_python_primary_are_strong_negative_walls"),
        1,
    ):
        title, requirement, expected = row
        cases.append(_case(f"walls-{index}", source, title, requirement, set(expected)))

    profile = harvest.load_profile_contract(PROFILE)
    fit_terms = profile["fit_terms"]
    rows = json.loads(FIXTURE.read_text(encoding="utf-8"))
    for row in rows:
        scored = harvest.score_posting(row, fit_terms)
        cases.append(
            Case(
                f"fixture-{row['id']}",
                FIXTURE.name,
                {
                    "title": row["title"],
                    "posting_text": row["jd_text"],
                    "candidate_mentions": _candidate_mentions(
                        row["title"], row["jd_text"]
                    ),
                },
                tuple(scored["negative_hits"]),
                tuple(row["expected_negative_hits"]),
            )
        )
    return cases


def public_posting_sanitizer(state: object) -> object:
    if not isinstance(state, dict) or set(state) != {
        "title",
        "posting_text",
        "candidate_mentions",
    }:
        raise ValueError(
            "E5 accepts only title, public posting_text, and candidate_mentions"
        )
    if not isinstance(state["title"], str) or not isinstance(
        state["posting_text"], str
    ):
        raise ValueError("E5 posting fields must be strings")
    if not isinstance(state["candidate_mentions"], list) or not all(
        isinstance(value, str) for value in state["candidate_mentions"]
    ):
        raise ValueError("E5 candidate_mentions must be a string list")
    return state


QUESTION = jev_client.Question(
    id="requirement_verdict",
    type="choice",
    instructions=(
        "Evaluate only the occurrences listed in `candidate_mentions`. Does at least one establish "
        "a hard requirement for this role: a non-target role title, a non-target technology stack, "
        "five or more required years, required infrastructure/container tooling, or Python as the "
        "primary required language?"
    ),
    criteria={
        HARD: "At least one such item is mandatory or clearly required for this role.",
        WAIVED: "The list is empty, or every listed mention is only an example, preference, or named alternative.",
    },
    fallback=WAIVED,
)


def _curve(decisions: Sequence[Decision]) -> tuple[CurveRow, ...]:
    rows = []
    for integer_floor in range(50, 100, 5):
        floor = integer_floor / 100
        eligible = [row for row in decisions if row.confidence >= floor]
        agreements = sum(row.answer == row.case.repo_label for row in eligible)
        rows.append(
            CurveRow(
                floor,
                agreements,
                len(eligible),
                len(decisions) - len(eligible),
                sum(
                    row.case.repo_label == HARD and row.answer == WAIVED
                    for row in eligible
                ),
                sum(
                    row.case.repo_label == WAIVED and row.answer == HARD
                    for row in eligible
                ),
            )
        )
    return tuple(rows)


def run_replay(
    cases: Sequence[Case],
    *,
    runs: int,
    sanitizer: Callable[[object], object],
    transport: jev_client.Transport | None = None,
    log_path: Path = jev_client.DEFAULT_LOG,
    usage_path: Path = jev_client.DEFAULT_USAGE,
) -> ReplayResult:
    planned_calls = len(cases) * runs
    planned_cost = (
        sum(jev_client.estimate_cost(case.state, QUESTION) for case in cases) * runs
    )
    decisions: list[Decision] = []
    actual_calls = 0
    cost = 0.0
    input_tokens = output_tokens = 0
    started = time.monotonic()
    for run in range(1, runs + 1):
        for case in cases:
            answer = jev_client.jev(
                case.state,
                [QUESTION],
                site="jrc-e5",
                sanitizer=sanitizer,
                transport=transport,
                log_path=log_path,
                usage_path=usage_path,
            )[0]
            actual_calls += int(answer.called)
            cost += answer.cost_usd
            input_tokens += answer.input_tokens
            output_tokens += answer.output_tokens
            decisions.append(
                Decision(run, case, str(answer.answer), answer.confidence, answer.model)
            )
    summaries = tuple(
        (
            run,
            sum(
                row.run == run and row.answer == row.case.repo_label
                for row in decisions
            ),
            len(cases),
        )
        for run in range(1, runs + 1)
    )
    return ReplayResult(
        tuple(decisions),
        _curve(decisions),
        summaries,
        planned_calls,
        actual_calls,
        planned_cost,
        cost,
        time.monotonic() - started,
        {row.model for row in decisions},
        input_tokens,
        output_tokens,
    )


def render_report(result: ReplayResult) -> str:
    lines = [
        "# E5 — Job Radar requirement-vs-example replay",
        "",
        "Shadow-only evaluation over public repository fixtures. The regex scorer remained authoritative; no call site, database, harvest behavior, or pipeline was changed.",
        "",
        "## Run receipt",
        "",
        f"- Planned / actual calls: **{result.planned_calls} / {result.actual_calls}**",
        f"- Planned conservative ceiling / actual cost: **${result.planned_cost_usd:.6f} / ${result.actual_cost_usd:.6f}**",
        f"- Wall time: **{result.wall_seconds:.2f}s**",
        f"- Model/version: **{', '.join(sorted(result.models))}**",
        f"- Tokens: **{result.input_tokens} input / {result.output_tokens} output**",
        "",
        "## Accuracy vs confidence threshold",
        "",
        "Agreement is reported as correct/considered; low-confidence rows abstain.",
        "",
        "| Floor | Agreement | Abstentions | False waives | False blocks |",
        "|---:|---:|---:|---:|---:|",
    ]
    for row in result.curve:
        lines.append(
            f"| {row.floor:.2f} | {row.agreement}/{row.considered} | {row.abstentions} | {row.false_waives} | {row.false_blocks} |"
        )
    lines += [
        "",
        "## Rerun variance",
        "",
        "Each cell is agreement/considered; abstentions; false-waives; false-blocks.",
        "",
        "| Floor | Run 1 | Run 2 | Run 3 |",
        "|---:|---|---|---|",
    ]
    for integer_floor in range(50, 100, 5):
        floor = integer_floor / 100
        cells = []
        for run in range(1, 4):
            row = _curve(
                [decision for decision in result.decisions if decision.run == run]
            )[integer_floor // 5 - 10]
            cells.append(
                f"{row.agreement}/{row.considered}; {row.abstentions}; {row.false_waives}; {row.false_blocks}"
            )
        lines.append(f"| {floor:.2f} | " + " | ".join(cells) + " |")
    lines += [
        "",
        "## Every currently-passing expected_negative_hits row",
        "",
        "Pass means Jev's top choice reproduced the row's binary hard-requirement vs waived/no-match label in all three runs. Exact regex hit names remain code-owned.",
        "",
        "| Row | Regex hits | Repo hits | Run 1 | Run 2 | Run 3 | Pass |",
        "|---|---|---|---|---|---|---|",
    ]
    by_case: dict[str, list[Decision]] = {}
    for decision in result.decisions:
        by_case.setdefault(decision.case.id, []).append(decision)
    for case_id, decisions in by_case.items():
        case = decisions[0].case
        answers = [f"{row.answer} ({row.confidence:.2f})" for row in decisions]
        passed = all(row.answer == case.repo_label for row in decisions)
        lines.append(
            f"| {case_id} | {', '.join(case.current_negative_hits) or '—'} | {', '.join(case.expected_negative_hits) or '—'} | "
            + " | ".join(answers)
            + f" | {'yes' if passed else 'no'} |"
        )
    all_pass = all(row.answer == row.case.repo_label for row in result.decisions)
    lines += [
        "",
        "## Pass bar and replacement read",
        "",
        f"- Reproduces every row in every run: **{'YES' if all_pass else 'NO'}**.",
        "- If it passed, it could replace the roughly 120-line context/waiver regex tower around `scraper/harvest.py:641` and `:679`; this experiment does not switch that call site.",
        f"- Honest read: **{'close on this frozen set, but still shadow-only' if all_pass else 'not close enough to replace the deterministic scorer'}**.",
        "- API-doc note: TypeSafe returns no separate Noul confidence; this replay therefore uses Choice, whose response includes confidence.",
        "",
    ]
    return "\n".join(lines)


def rescore_table_via_existing_script() -> str:
    completed = subprocess.run(
        [
            sys.executable,
            str(HERE / "rescore_fixture.py"),
            "--fixture",
            str(FIXTURE),
            "--profile",
            str(PROFILE),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError("existing rescore fixture script failed")
    return completed.stdout.strip()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", action="store_true")
    parser.add_argument("--real", action="store_true")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--max-calls", type=int, default=114)
    parser.add_argument("--max-usd", type=float, default=1.0)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--decision-log", type=Path, default=jev_client.DEFAULT_LOG)
    parser.add_argument("--usage-log", type=Path, default=jev_client.DEFAULT_USAGE)
    args = parser.parse_args(argv)
    cases = load_cases()
    calls = len(cases) * args.runs
    estimate = (
        sum(jev_client.estimate_cost(case.state, QUESTION) for case in cases)
        * args.runs
    )
    print(
        f"planned_calls={calls} estimated_cost_usd={estimate:.6f} hard_cap_usd={args.max_usd:.2f}"
    )
    if calls > args.max_calls or estimate > args.max_usd:
        print("ABORT: replay exceeds printed plan or hard cap")
        return 2
    if args.plan:
        return 0
    if not args.real:
        parser.error("choose --plan or --real")
    os.environ["JEV_DAILY_USD_CAP"] = str(args.max_usd)
    result = run_replay(
        cases,
        runs=args.runs,
        sanitizer=public_posting_sanitizer,
        log_path=args.decision_log,
        usage_path=args.usage_log,
    )
    if result.actual_calls != calls or result.actual_cost_usd > args.max_usd:
        raise RuntimeError("actual replay exceeded its printed plan")
    report = render_report(result)
    report += (
        "\n## Existing rescore_fixture.py before/after table\n\n"
        + rescore_table_via_existing_script()
        + "\n"
    )
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(report, encoding="utf-8")
    else:
        print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
