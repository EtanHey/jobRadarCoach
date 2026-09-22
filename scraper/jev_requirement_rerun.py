#!/usr/bin/env python3
"""E5: shadow-only Jev replay of Job Radar negative-rule occurrences."""

from __future__ import annotations

import argparse
import importlib
import importlib.util
import json
import math
import os
import random
import statistics
import time
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Literal, Sequence

import psycopg

from scraper import harvest

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
GOLEMS = Path(os.environ.get("GOLEMS_REPO", Path.home() / "Gits/golems"))
SHARED_JEV = GOLEMS / "packages/shared/src/lib/jev.py"
CHOICE_REPLAY = GOLEMS / "scripts/jev-choice-replay.py"
FIXTURE = HERE / "fixtures/job-radar-rescore-2026-08-11.json"
DATABASE_URL = "postgresql://postgres:postgres@127.0.0.1:54322/postgres"
SITE = "jrc-e5-rerun"
HARD = "hard_requirement"
WAIVED = "waived_mention"
FLOORS = tuple(value / 100 for value in range(50, 100, 5))
FIXED_FLOOR = 0.70
CONTEXT_RADIUS = 120
RESERVE_USD = 0.50
PRICE_PER_INPUT_TOKEN = 0.042 / 1_000_000
AssertionKind = Literal["exact", "subset", "disjoint", "excluded"]


def _load_path_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if not spec or not spec.loader:
        raise RuntimeError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


jev_client = _load_path_module("jrc_e5_shared_jev", SHARED_JEV)
choice_replay = _load_path_module("jrc_e5_choice_replay", CHOICE_REPLAY)
wilson = choice_replay.wilson


@dataclass(frozen=True)
class Assertion:
    kind: AssertionKind
    expected: frozenset[str] = frozenset()
    forbidden: frozenset[str] = frozenset()

    def evaluate(self, predicted: set[str]) -> bool | None:
        if self.kind == "excluded":
            return None
        if self.kind == "exact":
            return predicted == set(self.expected)
        if self.kind == "subset":
            return set(self.expected) <= predicted
        return set(self.forbidden).isdisjoint(predicted)


@dataclass(frozen=True)
class Occurrence:
    posting_id: str
    label: str
    mention: str
    start: int
    end: int
    scope: str
    tower_answer: str
    stratum: str
    case_id: str | None = None
    truth: str | None = None

    @property
    def key(self) -> str:
        return f"{self.posting_id}|{self.label}|{self.start}|{self.end}"


@dataclass(frozen=True)
class TruthCase:
    id: str
    title: str
    raw_jd: str
    assertion: Assertion
    occurrences: tuple[Occurrence, ...]


@dataclass(frozen=True)
class Observation:
    run: int
    key: str
    posting_id: str
    case_id: str | None
    label: str
    mention: str
    start: int
    end: int
    tower_answer: str
    truth: str | None
    answer: str
    confidence: float
    acted: bool
    source: str
    model: str
    input_tokens: int
    cost_usd: float
    wall_seconds: float
    stratum: str


@dataclass(frozen=True)
class CurveRow:
    floor: float
    jev_recall: float
    jev_precision: float
    tower_recall: float
    tower_precision: float
    jev_false_fires: int
    tower_false_fires: int
    abstentions: int


QUESTION = {
    "id": "requirement_verdict",
    "type": "choice",
    "instructions": (
        "Judge only the located occurrence. Is that occurrence a HARD REQUIREMENT "
        "of this role, or a WAIVED mention such as an example, alternative, "
        "nice-to-have, optional skill, or other-team context?"
    ),
    "criteria": {
        HARD: "The located occurrence is mandatory or clearly required for this role.",
        WAIVED: "The located occurrence is not required for this role.",
    },
    "fallback_answer": WAIVED,
}


def _param_rows(name: str) -> list[object]:
    module = importlib.import_module("scraper.test_harvest")
    marks = [
        mark for mark in getattr(module, name).pytestmark if mark.name == "parametrize"
    ]
    if len(marks) != 1:
        raise ValueError(f"expected one parametrize mark on {name}")
    return list(marks[0].args[1])


def candidate_occurrences(
    posting_id: str,
    title: str,
    raw_jd: str,
    *,
    stratum: str = "B",
    case_id: str | None = None,
) -> tuple[Occurrence, ...]:
    """Return stable per-match units over exactly title + newline + raw_jd."""
    combined = f"{title}\n{raw_jd}"
    found: list[Occurrence] = []
    for label, pattern, _weight, scope in harvest.NEGATIVE_RULES:
        haystack = title if scope == harvest.TITLE_ONLY else combined
        for match in pattern.finditer(haystack):
            waived = harvest._is_non_required_stack_context(label, haystack, match)
            waived = waived or harvest._is_example_list_occurrence(haystack, match)
            found.append(
                Occurrence(
                    posting_id=str(posting_id),
                    label=label,
                    mention=match.group(0),
                    start=match.start(),
                    end=match.end(),
                    scope=scope,
                    tower_answer=WAIVED if waived else HARD,
                    stratum=stratum,
                    case_id=case_id,
                )
            )
    return tuple(sorted(found, key=lambda row: (row.start, row.end, row.label)))


def occurrence_state(
    occurrence: Occurrence, title: str, raw_jd: str
) -> dict[str, object]:
    combined = f"{title}\n{raw_jd}"
    haystack = title if occurrence.scope == harvest.TITLE_ONLY else combined
    left = max(0, occurrence.start - CONTEXT_RADIUS)
    right = min(len(haystack), occurrence.end + CONTEXT_RADIUS)
    return {
        "title": title,
        "posting_text": raw_jd,
        "occurrence": {
            "label": occurrence.label,
            "mention": occurrence.mention,
            "start": occurrence.start,
            "end": occurrence.end,
            "scope": occurrence.scope,
            "context_start": left,
            "context_end": right,
            "context": haystack[left:right],
        },
    }


def public_posting_sanitizer(state: object) -> object:
    if not isinstance(state, dict) or set(state) != {
        "title",
        "posting_text",
        "occurrence",
    }:
        raise ValueError(
            "E5 state must contain title, posting_text, and occurrence only"
        )
    if not isinstance(state["title"], str) or not isinstance(
        state["posting_text"], str
    ):
        raise ValueError("E5 posting fields must be strings")
    locator = state["occurrence"]
    required = {
        "label",
        "mention",
        "start",
        "end",
        "scope",
        "context_start",
        "context_end",
        "context",
    }
    if not isinstance(locator, dict) or set(locator) != required:
        raise ValueError("E5 occurrence locator is invalid")
    if not all(
        isinstance(locator[key], str)
        for key in ("label", "mention", "scope", "context")
    ):
        raise ValueError("E5 occurrence strings are invalid")
    if not all(
        isinstance(locator[key], int) and not isinstance(locator[key], bool)
        for key in ("start", "end", "context_start", "context_end")
    ):
        raise ValueError("E5 occurrence offsets are invalid")
    if locator["end"] <= locator["start"] or len(
        locator["context"]
    ) > CONTEXT_RADIUS * 2 + len(locator["mention"]):
        raise ValueError("E5 occurrence bounds are invalid")
    return state


def _case(case_id: str, title: str, raw_jd: str, assertion: Assertion) -> TruthCase:
    occurrences = list(
        candidate_occurrences(case_id, title, raw_jd, stratum="A", case_id=case_id)
    )
    expected = set(assertion.expected)
    by_label: dict[str, list[int]] = defaultdict(list)
    for index, occurrence in enumerate(occurrences):
        by_label[occurrence.label].append(index)
    labelled: list[Occurrence] = []
    for index, occurrence in enumerate(occurrences):
        truth: str | None = None
        if assertion.kind == "disjoint" and occurrence.label in assertion.forbidden:
            truth = WAIVED
        elif assertion.kind == "exact":
            if occurrence.label not in expected:
                truth = WAIVED
            elif occurrence.tower_answer == HARD:
                truth = HARD
            elif not any(
                occurrences[item].tower_answer == HARD
                for item in by_label[occurrence.label]
            ):
                truth = HARD if index == by_label[occurrence.label][0] else WAIVED
            else:
                truth = WAIVED
        elif assertion.kind == "subset" and occurrence.label in expected:
            truth = HARD if occurrence.tower_answer == HARD else None
        labelled.append(Occurrence(**{**asdict(occurrence), "truth": truth}))
    return TruthCase(case_id, title, raw_jd, assertion, tuple(labelled))


def load_truth_cases() -> list[TruthCase]:
    cases: list[TruthCase] = []
    for index, row in enumerate(_param_rows("test_score_posting_rules"), 1):
        text, _positive, _senior, _keywords, expected = row
        cases.append(
            _case(f"score-{index}", text, "", Assertion("exact", frozenset(expected)))
        )
    for index, row in enumerate(_param_rows("test_live_triage_negative_rules"), 1):
        requirement, label, _weight = row
        cases.append(
            _case(
                f"triage-{index}",
                requirement,
                "",
                Assertion("exact", frozenset({label})),
            )
        )
    for index, row in enumerate(_param_rows("test_live_2026_08_10_role_controls"), 1):
        title, raw_jd, _positive, label = row
        assertion = (
            Assertion("subset", frozenset({label})) if label else Assertion("excluded")
        )
        cases.append(_case(f"role-{index}", title, raw_jd, assertion))
    for index, requirement in enumerate(
        _param_rows("test_high_year_requirements_match_common_jd_phrasings"), 1
    ):
        cases.append(
            _case(
                f"years-{index}",
                "Software Engineer",
                requirement,
                Assertion("exact", frozenset({"8-9+ years"})),
            )
        )
    for index, row in enumerate(
        _param_rows("test_polyglot_alternative_list_does_not_trigger_stack_negative"), 1
    ):
        _job_id, requirement, _positive = row
        cases.append(
            _case(
                f"polyglot-{index}",
                "Backend Software Engineer",
                requirement,
                Assertion("disjoint", forbidden=frozenset({"c#", "c++"})),
            )
        )
    for index, row in enumerate(
        _param_rows("test_required_infra_and_python_primary_are_strong_negative_walls"),
        1,
    ):
        title, requirement, expected = row
        cases.append(
            _case(
                f"walls-{index}",
                title,
                requirement,
                Assertion("subset", frozenset(expected)),
            )
        )
    for row in json.loads(FIXTURE.read_text(encoding="utf-8")):
        expected = frozenset(row["expected_negative_hits"])
        cases.append(
            _case(
                f"fixture-{row['id']}",
                row["title"],
                row["jd_text"],
                Assertion("exact", expected),
            )
        )
    return cases


def load_production_postings(
    database_url: str = DATABASE_URL,
) -> tuple[dict[str, tuple[str, str]], tuple[Occurrence, ...]]:
    postings: dict[str, tuple[str, str]] = {}
    occurrences: list[Occurrence] = []
    with psycopg.connect(database_url) as connection:
        connection.execute("set transaction read only")
        rows = connection.execute(
            "select id::text, coalesce(title, ''), raw_jd from public.postings "
            "where length(raw_jd) > 200 order by id"
        ).fetchall()
    for posting_id, title, raw_jd in rows:
        found = candidate_occurrences(posting_id, title, raw_jd)
        if found:
            postings[posting_id] = (title, raw_jd)
            occurrences.extend(found)
    return postings, tuple(occurrences)


def _usage_receipt(state_dir: Path, offset: int) -> tuple[int, float, str]:
    delta = choice_replay.usage_delta(state_dir / "usage.jsonl", offset)
    reservations = [row for row in delta if row.get("kind") == "reservation"]
    reconciliations = [row for row in delta if row.get("kind") == "reconciliation"]
    if len(reservations) != 1 or len(reconciliations) != 1:
        raise RuntimeError("usage ledger did not contain one reconciled call")
    if reservations[0].get("reservation_id") != reconciliations[0].get(
        "reservation_id"
    ):
        raise RuntimeError("usage reservation id did not reconcile")
    return (
        int(reconciliations[0]["input_tokens"]),
        sum(float(row["cost_usd"]) for row in delta),
        str(reconciliations[0].get("model", "unknown")),
    )


def score_occurrences(
    occurrences: Sequence[Occurrence],
    postings: dict[str, tuple[str, str]],
    *,
    run: int,
    state_dir: Path,
    transport: Callable[[dict[str, Any], str], dict[str, Any]] | None = None,
) -> tuple[Observation, ...]:
    state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    previous_key = os.environ.get("TYPESAFE_API_KEY")
    if transport is not None and not previous_key:
        os.environ["TYPESAFE_API_KEY"] = "offline-fake-transport"
    observations: list[Observation] = []
    try:
        for occurrence in occurrences:
            usage_path = state_dir / "usage.jsonl"
            offset = usage_path.stat().st_size if usage_path.exists() else 0
            title, raw_jd = postings[occurrence.posting_id]
            state = occurrence_state(occurrence, title, raw_jd)
            started = time.monotonic()
            answers = jev_client.jev_shadow(
                state,
                [QUESTION],
                public_posting_sanitizer,
                site=SITE,
                state_dir=state_dir,
                transport=transport,
                timeout_seconds=30,
            )
            elapsed = time.monotonic() - started
            if len(answers) != 1:
                raise RuntimeError("Jev returned an incomplete answer set")
            answer = answers[0]
            if (
                answer.get("source") != "jev"
                or answer.get("acted") is not False
                or answer.get("answer") not in {HARD, WAIVED}
            ):
                reason = choice_replay.fallback_reason(state_dir)
                raise RuntimeError(f"Jev fallback/non-shadow/invalid answer: {reason}")
            confidence = answer.get("confidence")
            if (
                isinstance(confidence, bool)
                or not isinstance(confidence, (int, float))
                or not math.isfinite(confidence)
            ):
                raise RuntimeError("Jev confidence was invalid")
            input_tokens, cost, model = _usage_receipt(state_dir, offset)
            observations.append(
                Observation(
                    run=run,
                    key=occurrence.key,
                    posting_id=occurrence.posting_id,
                    case_id=occurrence.case_id,
                    label=occurrence.label,
                    mention=occurrence.mention,
                    start=occurrence.start,
                    end=occurrence.end,
                    tower_answer=occurrence.tower_answer,
                    truth=occurrence.truth,
                    answer=str(answer["answer"]),
                    confidence=float(confidence),
                    acted=False,
                    source="jev",
                    model=model,
                    input_tokens=input_tokens,
                    cost_usd=cost,
                    wall_seconds=elapsed,
                    stratum=occurrence.stratum,
                )
            )
    finally:
        if transport is not None and previous_key is None:
            os.environ.pop("TYPESAFE_API_KEY", None)
    return tuple(observations)


def _rates(
    rows: Sequence[Observation], floor: float, answer_key: str
) -> tuple[float, float, int, int, int, int]:
    tp = fp = fn = abstain = 0
    for row in rows:
        if row.truth not in {HARD, WAIVED}:
            continue
        answer = getattr(row, answer_key)
        if answer_key == "answer" and row.confidence < floor:
            abstain += 1
            answer = "ABSTAIN"
        tp += answer == HARD and row.truth == HARD
        fp += answer == HARD and row.truth == WAIVED
        fn += answer != HARD and row.truth == HARD
    recall = tp / (tp + fn) if tp + fn else 0.0
    precision = tp / (tp + fp) if tp + fp else 0.0
    return recall, precision, tp, fp, fn, abstain


def threshold_curve(
    rows: Sequence[Observation], _cases: object = None
) -> tuple[CurveRow, ...]:
    result = []
    for floor in FLOORS:
        jr, jp, _jtp, jfp, _jfn, abstain = _rates(rows, floor, "answer")
        tr, tp, _ttp, tfp, _tfn, _ = _rates(rows, floor, "tower_answer")
        result.append(CurveRow(floor, jr, jp, tr, tp, jfp, tfp, abstain))
    return tuple(result)


def _question_payload_bytes(state: dict[str, object]) -> int:
    payload = {
        "state": state,
        "model": "jev-latest",
        "questions": {
            QUESTION["id"]: {
                key: value
                for key, value in QUESTION.items()
                if key not in {"id", "fallback_answer"}
            }
        },
    }
    return len(choice_replay.canonical_json(payload).encode("utf-8"))


def plan() -> dict[str, object]:
    cases = load_truth_cases()
    a_postings = {case.id: (case.title, case.raw_jd) for case in cases}
    a_occurrences = tuple(
        occurrence for case in cases for occurrence in case.occurrences
    )
    b_postings, b_occurrences = load_production_postings()
    calls = len(a_occurrences) * 3 + len(b_occurrences)
    estimate_bytes = sum(
        _question_payload_bytes(occurrence_state(row, *a_postings[row.posting_id])) * 3
        for row in a_occurrences
    ) + sum(
        _question_payload_bytes(occurrence_state(row, *b_postings[row.posting_id]))
        for row in b_occurrences
    )
    estimate = (estimate_bytes + calls * 1024) * PRICE_PER_INPUT_TOKEN
    return {
        "truth_cases": len(cases),
        "truth_scored_occurrences": sum(row.truth is not None for row in a_occurrences),
        "stratum_a_occurrences": len(a_occurrences),
        "stratum_b_rows": len(b_postings),
        "stratum_b_occurrences": len(b_occurrences),
        "planned_calls": calls,
        "estimated_cost_usd": estimate,
        "reserve_usd": RESERVE_USD,
    }


def _write_jsonl(path: Path, rows: Sequence[Observation]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(
                json.dumps(asdict(row), ensure_ascii=False, separators=(",", ":"))
                + "\n"
            )


def run_real(run_dir: Path) -> dict[str, object]:
    if run_dir.exists():
        raise RuntimeError("fresh run directory required")
    run_dir.mkdir(parents=True, mode=0o700)
    preflight = plan()
    if float(preflight["estimated_cost_usd"]) > RESERVE_USD:
        raise RuntimeError("planned estimated cost exceeds $0.50 reserve")
    cases = load_truth_cases()
    a_postings = {case.id: (case.title, case.raw_jd) for case in cases}
    a_occurrences = tuple(row for case in cases for row in case.occurrences)
    b_postings, b_occurrences = load_production_postings()
    old_cap = os.environ.get("JEV_DAILY_USD_CAP")
    old_site = os.environ.get("JEV_SITE_JRC_E5_RERUN")
    os.environ["JEV_DAILY_USD_CAP"] = str(RESERVE_USD)
    os.environ["JEV_SITE_JRC_E5_RERUN"] = "shadow"
    all_rows: list[Observation] = []
    started = time.monotonic()
    try:
        for run in range(1, 4):
            rows = score_occurrences(
                a_occurrences, a_postings, run=run, state_dir=run_dir / "state"
            )
            _write_jsonl(run_dir / "observations.jsonl", rows)
            all_rows.extend(rows)
        rows = score_occurrences(
            b_occurrences, b_postings, run=1, state_dir=run_dir / "state"
        )
        _write_jsonl(run_dir / "observations.jsonl", rows)
        all_rows.extend(rows)
    finally:
        if old_cap is None:
            os.environ.pop("JEV_DAILY_USD_CAP", None)
        else:
            os.environ["JEV_DAILY_USD_CAP"] = old_cap
        if old_site is None:
            os.environ.pop("JEV_SITE_JRC_E5_RERUN", None)
        else:
            os.environ["JEV_SITE_JRC_E5_RERUN"] = old_site
    if len(all_rows) != int(preflight["planned_calls"]):
        raise RuntimeError("actual calls did not match the printed plan")
    if any(row.acted or row.source != "jev" for row in all_rows):
        raise RuntimeError("run contained an acted or fallback decision")
    actual_cost = sum(row.cost_usd for row in all_rows)
    if actual_cost > RESERVE_USD:
        raise RuntimeError("actual cost exceeded the reserve")
    summary = {
        **preflight,
        "actual_calls": len(all_rows),
        "actual_cost_usd": actual_cost,
        "input_tokens": sum(row.input_tokens for row in all_rows),
        "wall_seconds": time.monotonic() - started,
        "models": sorted({row.model for row in all_rows}),
    }
    (run_dir / "summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    write_blind_sample(run_dir, b_postings, all_rows)
    return summary


def _read_observations(path: Path) -> list[Observation]:
    return [
        Observation(**json.loads(line))
        for line in path.read_text(encoding="utf-8").splitlines()
        if line
    ]


def write_blind_sample(
    run_dir: Path, postings: dict[str, tuple[str, str]], rows: Sequence[Observation]
) -> None:
    divergent = [
        row
        for row in rows
        if row.stratum == "B"
        and row.confidence >= FIXED_FLOOR
        and row.answer != row.tower_answer
    ]
    rng = random.Random(20260922)
    selected = rng.sample(divergent, min(60, len(divergent)))
    blind = []
    for index, row in enumerate(selected, 1):
        title, raw_jd = postings[row.posting_id]
        matching = next(
            candidate
            for candidate in candidate_occurrences(row.posting_id, title, raw_jd)
            if candidate.key == row.key
        )
        state = occurrence_state(matching, title, raw_jd)
        sides = [row.answer, row.tower_answer]
        random.Random(f"20260922-{row.key}").shuffle(sides)
        blind.append(
            {
                "sample_id": index,
                "key": row.key,
                "title": title,
                "posting_text": raw_jd,
                "occurrence": state["occurrence"],
                "side_a": sides[0],
                "side_b": sides[1],
                "judge": None,
            }
        )
    (run_dir / "blind-sample.json").write_text(
        json.dumps(blind, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _metric_line(
    rows: Sequence[Observation], floor: float, key: str
) -> tuple[str, int]:
    recall, precision, tp, fp, fn, abstain = _rates(rows, floor, key)
    rlo, rhi = wilson(tp, tp + fn)
    plo, phi = wilson(tp, tp + fp)
    return (
        f"recall {recall:.3f} (95% CI {rlo:.3f}–{rhi:.3f}); precision {precision:.3f} (95% CI {plo:.3f}–{phi:.3f}); TP/FP/FN/abstain {tp}/{fp}/{fn}/{abstain}",
        fp,
    )


def _adjudication_read(
    sample: list[dict[str, object]], observations: Sequence[Observation]
) -> tuple[int, int, int]:
    lookup = {row.key: row for row in observations if row.stratum == "B"}
    added = false_fires = judged = 0
    for item in sample:
        if item.get("judge") not in {HARD, WAIVED}:
            continue
        row = lookup[str(item["key"])]
        judged += 1
        added += (
            row.answer == HARD and row.tower_answer == WAIVED and item["judge"] == HARD
        )
        false_fires += (
            row.answer == HARD
            and row.tower_answer == WAIVED
            and item["judge"] == WAIVED
        )
    return added, false_fires, judged


def _set_agreement(
    rows: Sequence[Observation], cases: Sequence[TruthCase], run: int, *, tower: bool
) -> tuple[int, int, int]:
    labels = {rule[0] for rule in harvest.NEGATIVE_RULES}
    passed = considered = abstained = 0
    for case in cases:
        if case.assertion.kind == "excluded" or not case.occurrences:
            continue
        selected = [row for row in rows if row.run == run and row.case_id == case.id]
        if not tower and any(row.confidence < FIXED_FLOOR for row in selected):
            abstained += 1
            continue
        predicted = {
            row.label
            for row in selected
            if (row.tower_answer if tower else row.answer) == HARD
            and (tower or row.confidence >= FIXED_FLOOR)
        }
        assertion = Assertion(
            case.assertion.kind,
            frozenset(set(case.assertion.expected) & labels),
            frozenset(set(case.assertion.forbidden) & labels),
        )
        outcome = assertion.evaluate(predicted)
        if outcome is not None:
            considered += 1
            passed += outcome
    return passed, considered, abstained


def render_report(run_dir: Path, adjudications: Path, report_path: Path) -> str:
    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    rows = _read_observations(run_dir / "observations.jsonl")
    a_rows = [row for row in rows if row.stratum == "A" and row.truth is not None]
    b_rows = [row for row in rows if row.stratum == "B"]
    sample = json.loads(adjudications.read_text(encoding="utf-8"))
    added, false_fires, judged = _adjudication_read(sample, b_rows)
    added_ci = wilson(added, judged)
    false_fire_ci = wilson(false_fires, judged)
    jev_line, jev_fp = _metric_line(a_rows, FIXED_FLOOR, "answer")
    tower_line, tower_fp = _metric_line(a_rows, FIXED_FLOOR, "tower_answer")
    jr, _jp, jtp, _jfp, jfn, _ja = _rates(a_rows, FIXED_FLOOR, "answer")
    tr, _tp, ttp, _tfp, tfn, _ta = _rates(a_rows, FIXED_FLOOR, "tower_answer")
    jlo, _jhi = wilson(jtp, jtp + jfn)
    replace = jr >= tr and jlo >= tr and jev_fp <= tower_fp
    adder = not replace and added >= 10 and false_fires <= 2 * added
    verdict = "REPLACE" if replace else "ADDER-ONLY" if adder else "NO-GO"
    deciding = (
        f"Jev recall lower bound {jlo:.3f} vs tower point recall {tr:.3f}; false fires {jev_fp} vs {tower_fp}"
        if replace or not adder
        else f"{added} adjudicated-correct added HARD vs {false_fires} adjudicated false fires"
    )
    divergences = [
        row
        for row in b_rows
        if row.confidence >= FIXED_FLOOR and row.answer != row.tower_answer
    ]
    latencies = [row.wall_seconds for row in rows]
    per_label: list[str] = []
    for label in sorted({row.label for row in a_rows}):
        selected = [row for row in a_rows if row.label == label]
        per_label.append(
            f"| {label} | {_metric_line(selected, FIXED_FLOOR, 'answer')[0]} | {_metric_line(selected, FIXED_FLOOR, 'tower_answer')[0]} |"
        )
    curve_lines = []
    for row in threshold_curve(a_rows):
        curve_lines.append(
            f"| {row.floor:.2f} | {row.jev_recall:.3f} | {row.jev_precision:.3f} | {row.tower_recall:.3f} | {row.tower_precision:.3f} | {row.jev_false_fires} | {row.tower_false_fires} | {row.abstentions} |"
        )
    run_lines = []
    for run in range(1, 4):
        selected = [row for row in a_rows if row.run == run]
        run_lines.append(
            f"| {run} | {_metric_line(selected, FIXED_FLOOR, 'answer')[0]} |"
        )
    cost_per_occurrence = float(summary["actual_cost_usd"]) / int(
        summary["actual_calls"]
    )
    row_count = len({row.posting_id for row in rows})
    cost_per_row = float(summary["actual_cost_usd"]) / row_count
    tower_started = time.perf_counter()
    production_postings, _ = load_production_postings()
    for posting_id, (title, raw_jd) in production_postings.items():
        candidate_occurrences(posting_id, title, raw_jd)
    tower_seconds = time.perf_counter() - tower_started
    cases = load_truth_cases()
    set_lines = []
    for run in range(1, 4):
        jev_set = _set_agreement(a_rows, cases, run, tower=False)
        tower_set = _set_agreement(a_rows, cases, run, tower=True)
        set_lines.append(
            f"| {run} | {jev_set[0]}/{jev_set[1]} | {jev_set[2]} | "
            f"{tower_set[0]}/{tower_set[1]} |"
        )
    lines = [
        "# E5 rerun — Jev requirement occurrence replay",
        "",
        f"VERDICT: **{verdict}** — {deciding} at the precommitted 0.70 floor.",
        "",
        "## Scope and assumptions",
        "",
        "- Shadow only. No database writes, pipeline changes, call-site switch, hosted change, or production-service mutation.",
        '- Candidate unit is exactly `(posting_id, label, match_start, match_end)` from the 25 `NEGATIVE_RULES` over `title + "\\n" + raw_jd`; title-only rules retain their scope.',
        "- The five year assertions and three infra/Python wall assertions were loaded as required but project to zero candidates because their labels are outside the approved 25-label set.",
        "- Repo assertions are set-level, not occurrence-level. For repeated expected labels, truth localization uses the current tower's per-occurrence waiver result; this favors the reference and is a limitation of Stratum A, not independent hand annotation.",
        "- Rows with no negative-hit assertion are excluded. Polyglot exclusions use disjoint-set semantics against `{c#, c++}`.",
        "- Shared imports: `importlib.util.spec_from_file_location` loads `~/Gits/golems/packages/shared/src/lib/jev.py`; the same mechanism loads PR #112's `scripts/jev-choice-replay.py`, whose canonical serializer, usage-delta validation, fallback inspection, and Wilson implementation are reused.",
        "- Checkout assumption: local `feat/e5-rerun` started at local `master` merge `62df72b` (PR #318); sandbox policy prevented refreshing stale read-only `origin/master` (`33d37f4`).",
        "",
        "## Run receipt",
        "",
        f"- Planned / actual calls: **{summary['planned_calls']} / {summary['actual_calls']}**.",
        f"- Planned estimate / actual cost / hard reserve: **${summary['estimated_cost_usd']:.6f} / ${summary['actual_cost_usd']:.6f} / $0.500000**.",
        f"- Input tokens / model: **{summary['input_tokens']} / {', '.join(summary['models'])}**.",
        f"- Wall time: **{summary['wall_seconds']:.2f}s**; latency p50/p95: **{statistics.median(latencies):.3f}s / {statistics.quantiles(latencies, n=20)[18]:.3f}s**.",
        f"- Jev cost per row / occurrence: **${cost_per_row:.8f} / ${cost_per_occurrence:.8f}**.",
        f"- Tower measured CPU: **{tower_seconds:.6f}s total / {tower_seconds / max(1, len(production_postings)):.8f}s per candidate row / $0 API cost**.",
        f"- Recount: **{summary['stratum_b_rows']} Stratum B rows / {summary['stratum_b_occurrences']} occurrences** (not the stale 428/1168 estimate).",
        "",
        "## Stratum A — asserted truth",
        "",
        f"- Jev overall: {jev_line}.",
        f"- Tower overall: {tower_line}.",
        "",
        "| Label | Jev | Tower |",
        "|---|---|---|",
        *per_label,
        "",
        "### Threshold curve",
        "",
        "| Floor | Jev recall | Jev precision | Tower recall | Tower precision | Jev false fires | Tower false fires | Abstentions |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|",
        *curve_lines,
        "",
        "### Three-run variance",
        "",
        "| Run | Jev at 0.70 |",
        "|---:|---|",
        *run_lines,
        "",
        "### Set-assertion semantics",
        "",
        "Zero-candidate rows and rows with no negative-hit assertion are excluded from set agreement; a Jev case with any sub-floor occurrence is reported as abstained.",
        "",
        "| Run | Jev set-pass | Jev abstained cases | Tower set-pass |",
        "|---:|---:|---:|---:|",
        *set_lines,
        "",
        "## Stratum B — production-scale divergence",
        "",
        f"- At 0.70: **{len(divergences)} / {len(b_rows)}** occurrences diverged from the tower.",
        f"- Blind Codex adjudication: **{judged}** sampled divergences; **{added}** Jev-only HARD calls judged correct; **{false_fires}** Jev-only HARD calls judged false fires.",
        f"- Sample-rate estimates: added-correct **{added / judged:.3f}** (Wilson 95% CI **{added_ci[0]:.3f}–{added_ci[1]:.3f}**); Jev-added false-fire **{false_fires / judged:.3f}** (Wilson 95% CI **{false_fire_ci[0]:.3f}–{false_fire_ci[1]:.3f}**).",
        "- The judge file presented posting text, occurrence locator/context, and randomized side A/B answers; it did not identify Jev or tower.",
        "",
        "## Decision",
        "",
        f"**{verdict}** — {deciding}.",
        "",
    ]
    report = "\n".join(lines)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8")
    return verdict


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--plan", action="store_true")
    mode.add_argument("--real", action="store_true")
    mode.add_argument("--render", action="store_true")
    parser.add_argument("--run-dir", type=Path)
    parser.add_argument("--adjudications", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    if args.plan:
        value = plan()
        print(json.dumps(value, sort_keys=True))
        return 0 if value["estimated_cost_usd"] <= RESERVE_USD else 2
    if not args.run_dir:
        parser.error("--run-dir is required")
    if args.real:
        print(json.dumps(run_real(args.run_dir), sort_keys=True))
        return 0
    if not args.adjudications or not args.report:
        parser.error("--render requires --adjudications and --report")
    print(render_report(args.run_dir, args.adjudications, args.report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
