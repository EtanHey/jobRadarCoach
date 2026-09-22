"""Offline-validated provider boundary for the forward-scoring experiment."""

from __future__ import annotations

import os
import time
from collections import Counter
from collections.abc import Mapping
from functools import partial
from pathlib import Path
from typing import Any

from classifier import core, persistence
from scraper import brain, jev_client
from scraper.annotate import SUPPORTED_CODEX_CLI_VERSION, provider_payload_projection
from scraper.codex_process import verify_codex_version
from scraper.forward_scoring_inputs import verify_freeze_receipt
from scraper.forward_scoring_policy import parse_verdict

EXPERIMENT_CODEX_VERSION = "codex-cli 0.155.1"
REFERENCE_MODEL = "gpt-5.6-terra"
REFERENCE_REASONING = "xhigh"
SITE = "jrc-forward-scoring"
CAP_USD = 0.50
INCIDENT_RESERVATION_USD = 0.002688
REMAINING_CAP_USD = CAP_USD - INCIDENT_RESERVATION_USD


def execution_metadata() -> dict[str, object]:
    return {
        "codex_cli_version": EXPERIMENT_CODEX_VERSION,
        "production_codex_pin": SUPPORTED_CODEX_CLI_VERSION,
        "reference_model": REFERENCE_MODEL,
        "reference_reasoning_effort": REFERENCE_REASONING,
        "experiment_only_deviation": True,
        "scorer_version": persistence.SCORER_VERSION,
    }


def validate_frozen(manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Fail closed on the frozen cohort, truth, or provider projection."""

    rows = manifest.get("rows")
    expected = manifest.get("expected_locators")
    dropped = manifest.get("dropped")
    if (
        manifest.get("schema_version") != 1
        or not isinstance(rows, list)
        or not isinstance(expected, Mapping)
        or not isinstance(dropped, list)
    ):
        raise ValueError("invalid frozen manifest structure")
    if any(
        not isinstance(locator, str)
        or not locator
        or type(part) is not int
        or part not in {1, 2, 3}
        for locator, part in expected.items()
    ) or Counter(expected.values()) != Counter({1: 20, 2: 10, 3: 10}):
        raise ValueError("expected locator ledger must be exactly 20/10/10")

    accounted: set[str] = set()
    for item in [*rows, *dropped]:
        if not isinstance(item, Mapping):
            raise TypeError("invalid cohort entry")
        locator, part = item.get("locator"), item.get("part")
        if (
            not isinstance(locator, str)
            or locator in accounted
            or type(part) is not int
            or expected.get(locator) != part
        ):
            raise ValueError("cohort entry does not match its expected locator")
        accounted.add(locator)
    if accounted != set(expected):
        raise ValueError("expected locator ledger is incomplete")
    if any(
        not isinstance(item.get("reason"), str) or not item["reason"].strip()
        for item in dropped
    ):
        raise ValueError("dropped cohort entry requires a reason")
    if {row.get("part") for row in rows} != {1, 2, 3}:
        raise ValueError("included rows must retain all three parts")

    for row in rows:
        frozen, gold = row.get("frozen_input"), row.get("gold")
        if not isinstance(frozen, Mapping) or set(frozen) != {
            "hosted_payload",
            "reference_validation_profile",
            "history_policy",
        }:
            raise ValueError("frozen input fields differ from the approved contract")
        hosted = frozen["hosted_payload"]
        profile = frozen["reference_validation_profile"]
        if (
            frozen["history_policy"] != "excluded"
            or not isinstance(hosted, Mapping)
            or set(hosted) != {"professional_profile", "public_posting"}
            or not isinstance(profile, Mapping)
            or provider_payload_projection(hosted["public_posting"], profile)
            != dict(hosted)
        ):
            raise ValueError("hosted payload differs from the production projection")
        parsed_label = (
            parse_verdict(gold["verbatim"])
            if isinstance(gold, Mapping) and isinstance(gold.get("verbatim"), str)
            else None
        )
        if (
            not isinstance(gold, Mapping)
            or not isinstance(gold.get("verbatim"), str)
            or parsed_label is None
            or parsed_label != gold.get("label")
        ):
            raise ValueError("gold label does not match the approved parser")
        runs = row.get("jev", [])
        if (
            not isinstance(runs, list)
            or len(runs) > 1
            or any(
                not isinstance(item, Mapping) or item.get("run") != 1 for item in runs
            )
        ):
            raise ValueError("the experiment permits one Jev run only")
        attempt = row.get("jev_attempt")
        if attempt is not None and (
            not isinstance(attempt, Mapping) or dict(attempt) != {"run": 1}
        ):
            raise ValueError("invalid Jev attempt marker")
        if runs and attempt is None:
            raise ValueError("a Jev result requires its durable attempt marker")
    verify_freeze_receipt(manifest)
    return rows


def reference_brain(request: brain.BrainRequest, snapshot: Mapping[str, object]):
    verifier = partial(verify_codex_version, expected_version=EXPERIMENT_CODEX_VERSION)
    return brain.run_brain(
        request,
        snapshot,
        env={
            "BRAIN": "codex",
            "CODEX_MODEL": REFERENCE_MODEL,
            "CODEX_REASONING_EFFORT": REFERENCE_REASONING,
        },
        timeout_seconds=120,
        codex_version_verifier=verifier,
    )


def score_reference(
    row: Mapping[str, Any], runner: core.BrainRunner = reference_brain
) -> dict[str, object]:
    frozen = row["frozen_input"]
    hosted = frozen["hosted_payload"]
    diagnostics: list[str] = []
    started = time.monotonic()
    result = core.score_projected(
        hosted["professional_profile"],
        hosted["public_posting"],
        [],
        profile_snapshot=frozen["reference_validation_profile"],
        brain_runner=runner,
        diagnostic=diagnostics.append,
    )
    if result is None:
        category = diagnostics[-1] if diagnostics else "unknown"
        raise RuntimeError(f"reference scorer failed ({category})")
    return {
        "fit_score": result.annotation["fit_score"],
        "model": result.model,
        "scorer_version": persistence.SCORER_VERSION,
        "latency_seconds": time.monotonic() - started,
        "cost_per_row_usd": None,
    }


def question() -> jev_client.Question:
    return jev_client.Question(
        "pursuit_decision",
        "choice",
        "Judge professional fit for this exact public posting using only the supplied professional profile.",
        {"pursue": "actively pursue", "maybe": "human review", "no": "do not pursue"},
        "maybe",
    )


def jev_state(row: Mapping[str, Any]) -> dict[str, object]:
    return dict(row["frozen_input"]["hosted_payload"])


def score_jev(
    row: Mapping[str, Any],
    run_dir: Path,
    transport: jev_client.Transport | None = None,
) -> dict[str, object]:
    state = jev_state(row)

    def sanitizer(value: object) -> object:
        if not isinstance(value, Mapping) or dict(value) != state:
            raise ValueError("Jev state differs from the approved hosted payload")
        return state

    started = time.monotonic()
    answer = jev_client.jev(
        state,
        [question()],
        site=SITE,
        sanitizer=sanitizer,
        transport=transport,
        log_path=run_dir / "decisions.jsonl",
        usage_path=run_dir / "usage.jsonl",
    )[0]
    if answer.fallback_used or answer.acted or not answer.called:
        raise RuntimeError("Jev did not return a fresh shadow-only answer")
    return {
        "run": 1,
        "answer": answer.answer,
        "confidence": answer.confidence,
        "model": answer.model,
        "latency_seconds": time.monotonic() - started,
        "cost_usd": answer.cost_usd,
    }


def provider_environment():
    """Return the exact temporary Jev environment used by orchestration."""

    return {
        "JEV_DAILY_USD_CAP": str(REMAINING_CAP_USD),
        "JEV_SITE_JRC_FORWARD_SCORING": "shadow",
        "JEV_ENABLED": os.getenv("JEV_ENABLED", "1"),
    }
