"""Synthetic v1.1 calibration rules; no owner profile or real posting data."""

import copy
import hashlib
import json

import pytest

from classifier import calibration, core, projection, request
from classifier.test_core import SequenceBrain, posting, profile_snapshot, wire_annotation


POLICY = {
    "familiar_primary_languages": ["CedarScript"],
    "conditional_primary_languages": {"DuneLang": ["CedarScript"]},
    "unfamiliar_technologies": ["QuartzDB", "NimbusCloud"],
    "years_conditional": 6,
    "years_hard_block_from": 7,
    "backend_heavy_max_score": 59,
    "backend_years_no_from": 4,
    "frontend_parity": True,
    "neutral_nice_to_have": ["AgentMesh"],
}

LANGUAGE_ALIAS_POLICY = copy.deepcopy(POLICY)
LANGUAGE_ALIAS_POLICY["familiar_primary_languages"].extend(
    ["TypeScript", "Go", "C#"]
)
LANGUAGE_ALIAS_POLICY["conditional_primary_languages"]["Python"] = ["TypeScript"]

TECH_ALIAS_GROUPS = [
    ["Kubernetes", "k8s"],
    ["AWS", "Amazon Web Services"],
    ["GCP", "Google Cloud Platform"],
    ["Azure", "Microsoft Azure"],
    ["Postgres", "PostgreSQL"],
]
TECH_ALIAS_POLICY = copy.deepcopy(POLICY)
TECH_ALIAS_POLICY["unfamiliar_technologies"] = [
    name for aliases in TECH_ALIAS_GROUPS for name in aliases
]


def calibrated(facts, *, jd="Build a CedarScript product. " * 12, policy=POLICY):
    snapshot = profile_snapshot()
    snapshot["candidate.scorer_calibration"] = copy.deepcopy(policy)
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
    ([["DuneLang"]], 82),
    ([["OtherLang"]], 82),
    ([["CedarScript"]], 82),
])
def test_primary_language_alternatives(language_clauses, expected_score):
    result, _ = calibrated(facts(required_primary_language_clauses=language_clauses))
    assert result is not None
    assert result.annotation["fit_score"] == expected_score


@pytest.mark.parametrize(
    "language_clause",
    [
        ["TS"],
        ["JS"],
        ["Py", "TS"],
        ["Python3", "TypeScript"],
        ["Golang"],
        ["csharp"],
        ["Node.js"],
        ["nodejs"],
        ["TS/JS"],
        ["TS,JavaScript"],
        ["TS|JS"],
        ["TS or JS"],
    ],
)
def test_b1_language_normalizations_are_observable_with_one_required_technology(language_clause):
    result, _ = calibrated(
        facts(
            required_technologies=["NimbusCloud"],
            required_primary_language_clauses=[language_clause],
        ),
        policy=LANGUAGE_ALIAS_POLICY,
    )
    assert result is not None and result.annotation["fit_score"] == 82


@pytest.mark.parametrize(
    "language_clause",
    [
        ["TS"],
        ["JS"],
        ["Py", "TS"],
        ["Python3", "TypeScript"],
        ["Golang"],
        ["csharp"],
        ["Node.js"],
        ["nodejs"],
        ["TS/JS"],
        ["TS,JavaScript"],
        ["TS|JS"],
        ["TS or JS"],
    ],
)
def test_b1_language_normalizations_are_observable_at_conditional_years(language_clause):
    result, _ = calibrated(
        facts(
            required_years=6,
            required_primary_language_clauses=[language_clause],
        ),
        policy=LANGUAGE_ALIAS_POLICY,
    )
    assert result is not None and result.annotation["fit_score"] == 59


def test_conditional_language_clause_and_familiar_or_option_are_counted_once():
    alone, _ = calibrated(
        facts(
            required_technologies=["NimbusCloud"],
            required_primary_language_clauses=[["DuneLang"]],
        )
    )
    conditional_alternative, _ = calibrated(
        facts(
            required_technologies=["NimbusCloud"],
            required_primary_language_clauses=[["DuneLang", "CedarScript"]],
        )
    )
    familiar_or_option, _ = calibrated(
        facts(
            required_technologies=["NimbusCloud"],
            required_primary_language_clauses=[["CedarScript", "OtherLang"]],
        )
    )
    assert alone is not None and alone.annotation["fit_score"] == 59
    assert conditional_alternative is not None
    assert conditional_alternative.annotation["fit_score"] == 82
    assert familiar_or_option is not None and familiar_or_option.annotation["fit_score"] == 82


@pytest.mark.parametrize("aliases", TECH_ALIAS_GROUPS)
def test_required_technology_aliases_count_as_one_unfamiliar_requirement(aliases):
    result, _ = calibrated(
        facts(required_technologies=aliases),
        policy=TECH_ALIAS_POLICY,
    )
    assert result is not None and result.annotation["fit_score"] == 82


@pytest.mark.parametrize("language", ["TS", "Typescript", "typescript"])
def test_typescript_aliases_are_familiar(language):
    result, _ = calibrated(
        facts(required_primary_language_clauses=[[language]]),
        policy=LANGUAGE_ALIAS_POLICY,
    )
    assert result is not None and result.annotation["fit_score"] == 82


@pytest.mark.parametrize("language", ["JS", "JavaScript", "TS/JavaScript"])
def test_javascript_counts_as_familiar_with_typescript(language):
    result, _ = calibrated(
        facts(required_primary_language_clauses=[[language]]),
        policy=LANGUAGE_ALIAS_POLICY,
    )
    assert result is not None and result.annotation["fit_score"] == 82


@pytest.mark.parametrize(
    ("language_clause", "expected_score"),
    [
        (["Py", "TS"], 82),
        (["Python3", "TypeScript"], 82),
        (["Golang"], 82),
        (["Go"], 82),
        (["C#"], 82),
        (["csharp"], 82),
    ],
)
def test_common_primary_language_aliases_are_normalized(language_clause, expected_score):
    result, _ = calibrated(
        facts(required_primary_language_clauses=[language_clause]),
        policy=LANGUAGE_ALIAS_POLICY,
    )
    assert result is not None and result.annotation["fit_score"] == expected_score


@pytest.mark.parametrize(
    "language_clauses",
    [
        [["Node.js"]],
        [["CedarScript"], ["Node.js"]],
        [["CedarScript/Node.js"]],
    ],
)
def test_node_runtime_is_not_a_primary_language(language_clauses):
    result, _ = calibrated(facts(required_primary_language_clauses=language_clauses))
    assert result is not None and result.annotation["fit_score"] == 82


def test_one_required_unfamiliar_technology_does_not_cap_by_itself():
    required, _ = calibrated(facts(required_technologies=["NimbusCloud"]))
    assert required is not None and required.annotation["fit_score"] == 82


def test_two_required_unfamiliar_technologies_cap_at_review():
    result, _ = calibrated(
        facts(required_technologies=["QuartzDB", "NimbusCloud"])
    )
    assert result is not None and result.annotation["fit_score"] == 59


def test_two_unfamiliar_language_requirements_cap_at_review():
    result, _ = calibrated(
        facts(required_primary_language_clauses=[["OtherLang"], ["AnotherLang"]])
    )
    assert result is not None and result.annotation["fit_score"] == 59


def test_one_technology_and_one_language_requirement_count_as_two():
    result, _ = calibrated(
        facts(
            required_technologies=["NimbusCloud"],
            required_primary_language_clauses=[["OtherLang"]],
        )
    )
    assert result is not None and result.annotation["fit_score"] == 59


def test_one_unfamiliar_language_requirement_does_not_cap_by_itself():
    result, _ = calibrated(
        facts(required_primary_language_clauses=[["OtherLang"]])
    )
    assert result is not None and result.annotation["fit_score"] == 82


def test_unfamiliar_language_alternatives_count_as_one_requirement():
    result, _ = calibrated(
        facts(required_primary_language_clauses=[["OtherLang", "AnotherLang"]])
    )
    assert result is not None and result.annotation["fit_score"] == 82


def test_one_required_unfamiliar_with_backend_heavy_still_caps_at_review():
    result, _ = calibrated(
        facts(
            role_focus="backend",
            required_technologies=["NimbusCloud"],
        )
    )
    assert result is not None and result.annotation["fit_score"] == 59
    assert "backend_heavy" in result.calibration_rules


def test_nice_to_have_unfamiliar_does_not_cap():
    optional, _ = calibrated(
        facts(), jd="Nice to have NimbusCloud and AgentMesh. " * 10
    )
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
    prompt = req.prompt.casefold()
    assert "runtime" in prompt and "framework" in prompt
    assert "two or more distinct required unfamiliar technologies" in prompt
    assert (
        "one required unfamiliar technology or primary-language requirement does not cap by itself"
        in prompt
    )
    assert "calibration_facts" in req.output_schema["required"]
    assert "years_ignore_through" not in prompt
    assert "ignore required years below years_conditional" in prompt


def test_years_ignore_through_is_removed_from_the_policy_schema():
    assert "years_ignore_through" not in calibration.POLICY_FIELDS
    assert "years_ignore_through" not in POLICY
    assert calibration.validate_policy(POLICY) is POLICY
    with pytest.raises(ValueError):
        calibration.validate_policy({**POLICY, "years_ignore_through": 5})


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
