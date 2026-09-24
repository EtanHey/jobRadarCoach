"""Synthetic v1.1 calibration rules; no owner profile or real posting data."""

import copy
import hashlib
import json

import pytest

from classifier import core, projection, request
from classifier.test_core import SequenceBrain, posting, profile_snapshot, wire_annotation


POLICY = {
    "familiar_primary_languages": ["CedarScript"],
    "conditional_primary_languages": {"DuneLang": ["CedarScript"]},
    "unfamiliar_technologies": ["QuartzDB", "NimbusCloud"],
    "years_ignore_through": 5,
    "years_conditional": 6,
    "years_hard_block_from": 7,
    "backend_heavy_max_score": 59,
    "backend_years_no_from": 4,
    "frontend_parity": True,
    "neutral_nice_to_have": ["AgentMesh"],
}


def calibrated(facts, *, jd="Build a CedarScript product. " * 12):
    snapshot = profile_snapshot()
    snapshot["candidate.scorer_calibration"] = copy.deepcopy(POLICY)
    role = posting(jd)
    wire = wire_annotation(role["id"], fit_score=82)
    wire["calibration_facts"] = facts
    runner = SequenceBrain(wire)
    result = core.score_posting(snapshot, role, [], brain_runner=runner)
    return result, runner


def facts(**overrides):
    return {
        "required_years": None,
        "required_backend_years": None,
        "role_focus": "fullstack",
        "required_technologies": [],
        "required_primary_language_clauses": [],
        **overrides,
    }


@pytest.mark.parametrize(("years", "tech", "expected_score", "rule"), [
    (5, [], 82, None),
    (6, [], 59, "years_conditional"),
    (6, ["QuartzDB"], 39, "years_conditional_unfamiliar"),
    (7, [], 39, "years_hard_block"),
])
def test_years_caps(years, tech, expected_score, rule):
    result, _ = calibrated(facts(required_years=years, required_technologies=tech))
    assert result is not None
    assert result.annotation["fit_score"] == expected_score
    assert (rule in result.calibration_rules) if rule else not result.calibration_rules


@pytest.mark.parametrize(("language_clauses", "expected_score"), [
    ([["DuneLang", "CedarScript"]], 82),
    ([["DuneLang"]], 59),
    ([["OtherLang"]], 59),
    ([["CedarScript"]], 82),
])
def test_primary_language_alternatives(language_clauses, expected_score):
    result, _ = calibrated(facts(required_primary_language_clauses=language_clauses))
    assert result is not None
    assert result.annotation["fit_score"] == expected_score


def test_required_unfamiliar_caps_but_nice_to_have_does_not():
    required, _ = calibrated(facts(required_technologies=["NimbusCloud"]))
    optional, _ = calibrated(facts(), jd="Nice to have NimbusCloud and AgentMesh. " * 10)
    assert required is not None and required.annotation["fit_score"] == 59
    assert optional is not None and optional.annotation["fit_score"] == 82


@pytest.mark.parametrize(("focus", "backend_years", "expected_score"), [
    ("backend", None, 59),
    ("backend", 4, 39),
    ("backend", 5, 39),
    ("frontend", 5, 82),
    ("fullstack", None, 82),
])
def test_role_focus_and_backend_years(focus, backend_years, expected_score):
    result, _ = calibrated(facts(role_focus=focus, required_backend_years=backend_years))
    assert result is not None and result.annotation["fit_score"] == expected_score


def test_calibrated_request_contains_generic_rules_and_fact_schema():
    result, runner = calibrated(facts())
    assert result is not None
    req = runner.calls[0][0]
    assert "AgentMesh" in req.prompt and "nice-to-have" in req.prompt
    assert "frontend-heavy" in req.prompt
    assert "calibration_facts" in req.output_schema["required"]


def test_legacy_request_bytes_unchanged():
    req = request.build_request(
        projection.public_posting(posting()),
        projection.profile_contract(profile_snapshot()), [],
    )
    encoded = json.dumps(
        {"prompt": req.prompt, "schema": req.output_schema},
        ensure_ascii=False, sort_keys=True,
    ).encode()
    assert hashlib.sha256(encoded).hexdigest() == (
        "b4eb9d8c397990a449d1adfa6fcc24b55baa20a81114fa8cdb94017f08a4ce16"
    )


def test_bad_policy_or_facts_fail_closed():
    snapshot = profile_snapshot()
    snapshot["candidate.scorer_calibration"] = {**POLICY, "years_conditional": "six"}
    with pytest.raises(ValueError):
        projection.profile_contract(snapshot)
    result, _ = calibrated({**facts(), "required_years": "six"})
    assert result is None
