#!/usr/bin/env python3
"""Offline tests for the Luna job-posting annotator."""

from __future__ import annotations

import importlib.util
import json
import copy
import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest


HERE = Path(__file__).resolve().parent
ANNOTATE_PATH = HERE / "annotate.py"
PROFILE_PATH = HERE.parent / "profile.example.yaml"
FIXTURE_PATH = HERE / "fixtures" / "luna-postings.json"
CALIBRATION_PATH = HERE / "fixtures" / "luna-ranking-calibration-2026-08-26.json"


def load_annotate_module():
    spec = importlib.util.spec_from_file_location("job_feed_annotate", ANNOTATE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def posting(case: str) -> dict[str, object]:
    fixtures = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    # A missing named fixture must fail the test loudly.
    return next(item for item in fixtures if item["case"] == case)  # skipcq: PTC-W0063


class SequenceRunner:
    def __init__(self, *results: object) -> None:
        self.results = list(results)
        self.calls: list[tuple[str, dict[str, object]]] = []

    def __call__(self, prompt: str, schema: dict[str, object]) -> object:
        self.calls.append((prompt, schema))
        result = self.results.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result


REASON_FACTORS = [
    "product_role_match",
    "stack_domain_evidence",
    "seniority_gap",
    "employer_type",
    "preferences",
]


def structured_annotation(
    posting_id: str,
    *,
    employer_type: str = "direct",
    seniority_real: bool | None = False,
    fit_score: int = 72,
    fit_tier: str = "good",
    recommendation: str = "apply",
    fit_line: str = "Good evidence-backed fit.",
    fit_line_evidence_ids: list[str] | None = None,
) -> dict[str, object]:
    posting_evidence = f"posting:{posting_id}"
    if fit_line_evidence_ids is None:
        fit_line_evidence_ids = [posting_evidence, "example-project"]
    evidence_by_factor = {
        "product_role_match": [posting_evidence, "example-project"],
        "stack_domain_evidence": [posting_evidence, "example-workflow"],
        "seniority_gap": [posting_evidence, "profile:tenure"],
        "employer_type": [posting_evidence],
        "preferences": [posting_evidence, "profile:preferences"],
    }
    basis_by_factor = {
        "product_role_match": "comparison",
        "stack_domain_evidence": "comparison",
        "seniority_gap": "comparison",
        "employer_type": "posting",
        "preferences": "comparison",
    }
    return {
        "employer_type": employer_type,
        "seniority_real": seniority_real,
        "fit_score": fit_score,
        "fit_tier": fit_tier,
        "recommendation": recommendation,
        "reasons": [
            {
                "factor": factor,
                "basis": basis_by_factor[factor],
                "assessment": "positive",
                "evidence_ids": evidence_by_factor[factor],
                "detail": f"Evidence-backed {factor.replace('_', ' ')} assessment.",
            }
            for factor in REASON_FACTORS
        ],
        "fit_line": fit_line,
        "fit_line_evidence_ids": fit_line_evidence_ids,
    }


def safe_projection(*, relocation: bool = True) -> dict[str, object]:
    def signal(
        evidence_id: str,
        tags: list[str],
        claim: str,
    ) -> dict[str, object]:
        return {
            "evidence_id": evidence_id,
            "tags": tags,
            "claim": claim,
            "ownership": {
                "verified_scope": f"Verified scope for {evidence_id}.",
                "exclusions": [f"Excluded ownership for {evidence_id}."],
            },
            "status": "verified",
        }

    return {
        "projection_version": 1,
        "candidate": {
            "positioning": "Product-minded full-stack software engineer",
            "tenure_years": 3.7,
            "location": "Example City",
            "fit_terms": ["frontend", "agents", "mcp"],
            "open_to": {
                "geographies": ["Example City", "Remote"],
                "work_modes": ["on-site", "hybrid", "remote"],
                "relocation": relocation,
            },
            "preferences": {
                "product_company": "preferred",
                "experience_gap": {
                    "max_years_below_requirement": 1.0,
                    "treatment": "weigh-not-wall",
                },
            },
        },
        "fit_signals": [
            signal(
                "voice-agent-tool-calling",
                ["agents", "voice", "tool-calling"],
                "Shipped production voice-agent tool calling.",
            ),
            signal(
                "brainlayer",
                ["agents", "mcp"],
                "Persistent-memory MCP for AI agents.",
            ),
            signal(
                "example-workflow",
                ["claude-code", "product-shipping"],
                "Used an AI-assisted workflow in shipped-product work.",
            ),
            signal(
                "example-project",
                ["product-shipping", "fullstack"],
                "Shipped an example product.",
            ),
        ],
        "constraints": {
            "global_never_claims": ["Kubernetes", "Kafka", "Redis"],
            "evidence_scoped_prohibitions": {
                "voice-agent-tool-calling": [
                    "MCP",
                    "built a voice application's function-calling",
                ],
                "unified-integration-layer": [
                    "any import VOLUME — the candidate's own code comment says the only known connection is stale Workstream data"
                ],
                "example-project": ["owned unverified backend work"],
            },
        },
    }


def write_safe_contract(
    path: Path,
    projection: dict[str, object],
    *,
    contract_version: int = 1,
    private_name: str = "LEGACY_PRIVATE_CONTACT_SENTINEL",
) -> None:
    safe_json = json.dumps(projection, ensure_ascii=False, indent=2, sort_keys=True)
    path.write_text(
        "\n".join(
            [
                f"contract_version: {contract_version}",
                "profile:",
                f"  positioning: {private_name}",
                "artifacts:",
                "- path: /Users/private/LEGACY_PATH_SENTINEL.pdf",
                "connectors:",
                "- name: LEGACY_CONNECTOR_SENTINEL",
                "raw_private_note: LEGACY_RAW_NOTE_SENTINEL",
                "generated_from:",
                "  path: career/evidence-ledger.yaml",
                "safe_radar_projection:",
                *[f"  {line}" for line in safe_json.splitlines()],
                "",
            ]
        ),
        encoding="utf-8",
    )


def refresh_calibration_checksum(fixture: dict[str, object]) -> None:
    canonical_cases = json.dumps(
        fixture["cases"],
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    fixture["snapshot"]["snapshot_checksum"] = (
        f"sha256:{hashlib.sha256(canonical_cases).hexdigest()}"
    )


def verified_calibration_fixture() -> dict[str, object]:
    """Return synthetic provenance around reviewed public cases for unit testing."""

    fixture = json.loads(CALIBRATION_PATH.read_text(encoding="utf-8"))
    snapshot = fixture["snapshot"]
    snapshot.update(
        {
            "snapshot_id": "synthetic-verified-supabase-unit-test",
            "source_kind": "verified_supabase_export",
            "source_label": "Synthetic verified Supabase export for unit testing",
            "source_checksum": "sha256:"
            + hashlib.sha256(
                b"synthetic verified Supabase export unit fixture"
            ).hexdigest(),
            "supabase_export_verified": True,
            "provenance_status": "verified",
            "provenance_blocker": None,
        }
    )
    for index, case in enumerate(fixture["cases"], start=1):
        case["source_decision_id"] = f"test-only-decision-{index}"
    fixture["cases"].append(
        {
            "source_decision_id": "test-only-decision-fit-skip",
            "source_record_key": "test-only-record-fit-skip",
            "human_verdict": "skip",
            "human_rank": 3,
            "decision_basis": "fit",
            "pair_eligible": True,
            "decision_note": (
                "Test-only evidence-backed mismatch: the public role requires "
                "embedded C++, semiconductor firmware, and ten years of experience."
            ),
            "posting": {
                "id": "synthetic-fit-skip",
                "title": "Synthetic Embedded Systems Role",
                "company": "Example Product Company",
                "location": "Remote",
                "url": "https://example.com/jobs/synthetic-fit-skip",
                "jd_text": (
                    "This synthetic public unit-test posting requires ten years of "
                    "embedded C++ firmware development for semiconductor devices, "
                    "hardware bring-up, real-time operating systems, and board-level "
                    "debugging. Product web experience is explicitly out of scope."
                ),
            },
        }
    )
    refresh_calibration_checksum(fixture)
    return fixture


def test_schema_requires_structured_fit_ranking_fields() -> None:
    luna = load_annotate_module()

    assert luna.MODEL_FIELDS == {
        "employer_type",
        "seniority_real",
        "fit_score",
        "fit_tier",
        "recommendation",
        "reasons",
        "fit_line",
        "fit_line_evidence_ids",
    }
    assert set(luna.LUNA_SCHEMA["required"]) == luna.MODEL_FIELDS
    properties = luna.LUNA_SCHEMA["properties"]
    assert properties["fit_score"] == {
        "type": "integer",
        "minimum": 0,
        "maximum": 100,
    }
    assert properties["fit_tier"]["enum"] == ["strong", "good", "stretch", "weak"]
    assert properties["recommendation"]["enum"] == [
        "apply",
        "referral",
        "review",
        "skip",
    ]
    assert properties["fit_line_evidence_ids"] == {
        "type": "array",
        "minItems": 2,
        "items": {"type": "string", "minLength": 1},
    }
    reasons = properties["reasons"]
    assert reasons["type"] == "array"
    assert reasons["minItems"] == 5
    assert reasons["maxItems"] == 5
    assert reasons["items"]["additionalProperties"] is False
    assert set(reasons["items"]["required"]) == {
        "factor",
        "basis",
        "assessment",
        "evidence_ids",
        "detail",
    }
    assert reasons["items"]["properties"]["factor"]["enum"] == [
        "product_role_match",
        "stack_domain_evidence",
        "seniority_gap",
        "employer_type",
        "preferences",
    ]
    assert reasons["items"]["properties"]["basis"]["enum"] == [
        "posting",
        "comparison",
    ]


@pytest.mark.parametrize(
    ("case", "model_data", "expected"),
    [
        (
            "agency",
            structured_annotation(
                "4449531562",
                employer_type="agency",
                seniority_real=None,
                fit_score=54,
                fit_tier="stretch",
                recommendation="review",
                fit_line="Node.js and TypeScript overlap, but the client and product are undisclosed.",
            ),
            ("agency", None),
        ),
        (
            "direct",
            structured_annotation(
                "4377864561",
                seniority_real=True,
                fit_score=84,
                fit_tier="strong",
                recommendation="apply",
                fit_line="Strong React, TypeScript, design-system and product-UI overlap.",
            ),
            ("direct", True),
        ),
        (
            "inflated-senior",
            structured_annotation(
                "senior-example",
                seniority_real=False,
                fit_score=76,
                fit_tier="good",
                recommendation="apply",
                fit_line="Good full-stack overlap; the senior title only asks for two years.",
            ),
            ("direct", False),
        ),
        (
            "weak-fit",
            structured_annotation(
                "weak-example",
                seniority_real=True,
                fit_score=12,
                fit_tier="weak",
                recommendation="skip",
                fit_line="Weak fit — embedded C++, semiconductors and ten years are outside the profile.",
            ),
            ("direct", True),
        ),
    ],
)
def test_annotate_validates_fixture_cases(
    case: str,
    model_data: dict[str, object],
    expected: tuple[str, bool | None],
) -> None:
    luna = load_annotate_module()
    runner = SequenceRunner({"status": "ok", "data": model_data})

    result = luna.annotate(posting(case), runner=runner, profile_path=PROFILE_PATH)

    assert result is not None
    assert set(result) == {
        "employer_type",
        "seniority_real",
        "fit_score",
        "fit_tier",
        "recommendation",
        "reasons",
        "fit_line",
        "fit_line_evidence_ids",
        "luna_status",
    }
    assert (result["employer_type"], result["seniority_real"]) == expected
    assert result["luna_status"] == "ok"
    assert len(result["fit_line"]) <= 160
    if case == "weak-fit":
        assert result["fit_line"].startswith("Weak fit —")


def test_safe_profile_contract_includes_only_reviewed_ranking_evidence() -> None:
    luna = load_annotate_module()

    profile = luna._load_safe_profile_contract(PROFILE_PATH)

    assert profile["projection_version"] == 1
    assert profile["candidate"]["open_to"] == {
        "geographies": ["Example City", "Remote"],
        "work_modes": ["hybrid", "remote"],
        "relocation": False,
    }
    assert profile["candidate"]["preferences"] == {
        "product_company": "preferred",
        "experience_gap": {
            "max_years_below_requirement": 1.0,
            "treatment": "weigh-not-wall",
        },
    }
    signals = profile["fit_signals"]
    by_id = {signal["evidence_id"]: signal for signal in signals}
    assert set(by_id) == {"example-project", "example-workflow"}
    serialized = json.dumps(profile, ensure_ascii=False, sort_keys=True)
    assert (
        "Do not claim infrastructure ownership."
        in profile["constraints"]["evidence_scoped_prohibitions"]["example-project"]
    )
    assert "Do not invent candidate experience." in profile["constraints"]["global_never_claims"]
    assert "/Users/" not in serialized


def test_prompt_uses_safe_profile_contract_without_private_connectors(
    tmp_path: Path,
) -> None:
    luna = load_annotate_module()
    private_name = "PRIVATE_NAME_SENTINEL"
    profile_path = tmp_path / "profile.yaml"
    write_safe_contract(profile_path, safe_projection(), private_name=private_name)
    runner = SequenceRunner(
        {
            "status": "ok",
            "data": structured_annotation(
                "4449531562",
                employer_type="agency",
                seniority_real=None,
                fit_score=55,
                fit_tier="stretch",
                recommendation="review",
                fit_line="Relevant backend overlap, but the end employer is undisclosed.",
            ),
        }
    )

    luna.annotate(posting("agency"), runner=runner, profile_path=profile_path)

    prompt, schema = runner.calls[0]
    assert "Product-minded full-stack software engineer" in prompt
    assert "Backend Engineer" in prompt
    assert "Gotfriends" in prompt
    assert "Do not use tools or modify files" in prompt
    assert "product and role match" in prompt
    assert "demonstrated stack and domain evidence" in prompt
    assert "less than one year" in prompt
    assert "Allowed geography must not reduce fit" in prompt
    assert "product-company preference" in prompt
    assert "An explicit human verdict is authoritative" in prompt
    assert private_name.casefold() not in prompt.casefold()
    assert "/Users/" not in prompt
    assert schema["additionalProperties"] is False


def test_safe_profile_contract_consumes_only_projection_and_accepts_false_relocation(
    tmp_path: Path,
) -> None:
    luna = load_annotate_module()
    profile_path = tmp_path / "profile.yaml"
    write_safe_contract(profile_path, safe_projection(relocation=False))

    profile = luna._load_safe_profile_contract(profile_path)
    prompt = luna._build_prompt(posting("direct"), profile)

    assert profile["candidate"]["open_to"]["relocation"] is False
    for forbidden in (
        "LEGACY_PRIVATE_CONTACT_SENTINEL",
        "LEGACY_PATH_SENTINEL",
        "LEGACY_CONNECTOR_SENTINEL",
        "LEGACY_RAW_NOTE_SENTINEL",
        "/Users/private",
    ):
        assert forbidden not in json.dumps(profile, ensure_ascii=False)
        assert forbidden not in prompt


@pytest.mark.parametrize(
    "case",
    [
        "wrong_contract_version",
        "wrong_projection_version",
        "unknown_candidate_key",
        "path_like_safe_value",
        "unverified_signal",
        "duplicate_signal_id",
        "malformed_ownership",
        "unknown_constraint_key",
    ],
)
def test_safe_profile_contract_rejects_non_whitelisted_or_untrusted_values(
    tmp_path: Path, case: str
) -> None:
    luna = load_annotate_module()
    projection = safe_projection()
    contract_version = 1
    if case == "wrong_contract_version":
        contract_version = 2
    elif case == "wrong_projection_version":
        projection["projection_version"] = 2
    elif case == "unknown_candidate_key":
        projection["candidate"]["contact"] = "RAW_CONTACT_SENTINEL"
    elif case == "path_like_safe_value":
        projection["candidate"]["positioning"] = "/Users/private/resume.pdf"
    elif case == "unverified_signal":
        projection["fit_signals"][0]["status"] = "approximate"
    elif case == "duplicate_signal_id":
        projection["fit_signals"].append(copy.deepcopy(projection["fit_signals"][0]))
    elif case == "malformed_ownership":
        projection["fit_signals"][0]["ownership"] = "built everything"
    elif case == "unknown_constraint_key":
        projection["constraints"]["raw_private_note"] = "RAW_PRIVATE_NOTE_SENTINEL"
    profile_path = tmp_path / f"{case}.yaml"
    write_safe_contract(
        profile_path,
        projection,
        contract_version=contract_version,
    )

    with pytest.raises(ValueError):
        luna._load_safe_profile_contract(profile_path)


@pytest.mark.parametrize(
    "absolute_path",
    [
        "/private/secret.txt",
        "/tmp",
        "/etc",
        r"C:\private\secret.txt",
        "D:/private/secret.txt",
        r"\\server\share\secret.txt",
        "file:///private/secret.txt",
    ],
)
def test_safe_profile_contract_recursively_rejects_absolute_paths(
    tmp_path: Path, absolute_path: str
) -> None:
    luna = load_annotate_module()
    projection = safe_projection()
    projection["fit_signals"][0]["ownership"]["exclusions"] = [
        f"Private source was {absolute_path}"
    ]
    profile_path = tmp_path / "unsafe-path.yaml"
    write_safe_contract(profile_path, projection)

    with pytest.raises(ValueError, match="path-like"):
        luna._load_safe_profile_contract(profile_path)


def test_safe_profile_contract_allows_urls_and_slash_containing_prose(
    tmp_path: Path,
) -> None:
    luna = load_annotate_module()
    projection = safe_projection()
    projection["fit_signals"][0]["claim"] = (
        "Reviewed https://example.com/docs/profile for frontend/backend and "
        "product/role evidence."
    )
    profile_path = tmp_path / "safe-slashes.yaml"
    write_safe_contract(profile_path, projection)

    loaded = luna._load_safe_profile_contract(profile_path)

    assert loaded["fit_signals"][0]["claim"] == projection["fit_signals"][0]["claim"]


def test_malformed_output_retries_once_then_returns_invalid_status() -> None:
    luna = load_annotate_module()
    runner = SequenceRunner(
        {
            "status": "ok",
            "data": {
                "employer_type": "headhunter",
                "seniority_real": "maybe",
                "fit_line": "Looks good",
            },
        },
        {"status": "ok", "text": "not json"},
    )

    result = luna.annotate(posting("agency"), runner=runner, profile_path=PROFILE_PATH)

    assert result == {
        "employer_type": "unknown",
        "seniority_real": None,
        "fit_score": 0,
        "fit_tier": "weak",
        "recommendation": "review",
        "reasons": [],
        "fit_line": "",
        "fit_line_evidence_ids": [],
        "luna_status": "invalid",
    }
    assert len(runner.calls) == 2


def test_overlong_fit_line_is_invalid() -> None:
    luna = load_annotate_module()
    model_data = structured_annotation(
        "weak-example",
        seniority_real=True,
        fit_score=12,
        fit_tier="weak",
        recommendation="skip",
        fit_line="Weak fit — " + "x" * 151,
    )
    runner = SequenceRunner(
        {"status": "ok", "data": model_data},
        {"status": "ok", "text": "still invalid"},
    )

    result = luna.annotate(
        posting("weak-fit"), runner=runner, profile_path=PROFILE_PATH
    )

    assert result is not None
    assert result["luna_status"] == "invalid"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("fit_score", 101),
        ("fit_score", True),
        ("fit_tier", "excellent"),
        ("recommendation", "hire"),
    ],
)
def test_invalid_structured_ranking_values_fail_closed(
    field: str, value: object
) -> None:
    luna = load_annotate_module()
    invalid = structured_annotation("4377864561")
    invalid[field] = value
    runner = SequenceRunner(
        {"status": "ok", "data": invalid},
        {"status": "ok", "data": invalid},
    )

    result = luna.annotate(posting("direct"), runner=runner, profile_path=PROFILE_PATH)

    assert result == luna.INVALID_ANNOTATION


def test_tier_score_mismatch_and_unbacked_reasons_fail_closed() -> None:
    luna = load_annotate_module()
    tier_mismatch = structured_annotation("4377864561", fit_score=81, fit_tier="weak")
    unbacked = structured_annotation("4377864561")
    unbacked["reasons"][0]["evidence_ids"] = ["invented-resume-evidence"]
    runner = SequenceRunner(
        {"status": "ok", "data": tier_mismatch},
        {"status": "ok", "data": unbacked},
    )

    result = luna.annotate(posting("direct"), runner=runner, profile_path=PROFILE_PATH)

    assert result == luna.INVALID_ANNOTATION


@pytest.mark.parametrize(
    "case",
    [
        "global_never_claim_fit_line",
        "global_never_claim_detail",
        "voice_signal_claims_mcp",
        "posting_only_claims_candidate_experience",
        "comparison_missing_profile_evidence",
    ],
)
def test_prohibited_or_unsupported_candidate_claims_fail_closed(
    tmp_path: Path, case: str
) -> None:
    luna = load_annotate_module()
    profile_path = tmp_path / "profile.yaml"
    write_safe_contract(profile_path, safe_projection())
    invalid = structured_annotation("4377864561")
    if case == "global_never_claim_fit_line":
        invalid["fit_line"] = "Strong Kubernetes experience matches the role."
    elif case == "global_never_claim_detail":
        invalid["reasons"][1]["detail"] = (
            "Candidate has production Kubernetes experience."
        )
    elif case == "voice_signal_claims_mcp":
        invalid["reasons"][1]["evidence_ids"] = [
            "posting:4377864561",
            "voice-agent-tool-calling",
        ]
        invalid["reasons"][1]["detail"] = "Candidate built an MCP voice tool."
    elif case == "posting_only_claims_candidate_experience":
        invalid["reasons"][3]["detail"] = "Candidate has direct-employer experience."
    elif case == "comparison_missing_profile_evidence":
        invalid["reasons"][0]["evidence_ids"] = ["posting:4377864561"]
    runner = SequenceRunner(
        {"status": "ok", "data": invalid},
        {"status": "ok", "data": invalid},
    )

    result = luna.annotate(posting("direct"), runner=runner, profile_path=profile_path)

    assert result == luna.INVALID_ANNOTATION


def test_genuine_mcp_claim_is_accepted_only_with_genuine_profile_evidence(
    tmp_path: Path,
) -> None:
    luna = load_annotate_module()
    profile_path = tmp_path / "profile.yaml"
    write_safe_contract(profile_path, safe_projection())
    valid = structured_annotation("4377864561")
    valid["reasons"][1]["evidence_ids"] = [
        "posting:4377864561",
        "brainlayer",
    ]
    valid["reasons"][1]["detail"] = "Candidate built a persistent-memory MCP."
    runner = SequenceRunner({"status": "ok", "data": valid})

    result = luna.annotate(posting("direct"), runner=runner, profile_path=profile_path)

    assert result is not None
    assert result["luna_status"] == "ok"
    assert result["reasons"][1]["evidence_ids"] == [
        "posting:4377864561",
        "brainlayer",
    ]


@pytest.mark.parametrize(
    ("fit_line", "evidence_ids"),
    [
        (
            "Strong MCP voice-agent evidence matches the role.",
            ["posting:4377864561", "voice-agent-tool-calling"],
        ),
        (
            "Strong fit because the candidate owned unverified backend work.",
            ["posting:4377864561", "example-project"],
        ),
    ],
)
def test_fit_line_rejects_claims_forbidden_by_its_cited_evidence(
    tmp_path: Path, fit_line: str, evidence_ids: list[str]
) -> None:
    luna = load_annotate_module()
    profile_path = tmp_path / "profile.yaml"
    write_safe_contract(profile_path, safe_projection())
    invalid = structured_annotation(
        "4377864561",
        fit_line=fit_line,
        fit_line_evidence_ids=evidence_ids,
    )
    runner = SequenceRunner(
        {"status": "ok", "data": invalid},
        {"status": "ok", "data": invalid},
    )

    result = luna.annotate(posting("direct"), runner=runner, profile_path=profile_path)

    assert result == luna.INVALID_ANNOTATION


@pytest.mark.parametrize(
    "evidence_ids",
    [
        ["posting:4377864561"],
        ["posting:4377864561", "invented-resume-evidence"],
        ["posting:4377864561", "example-project", "example-project"],
        ["example-project", "brainlayer"],
    ],
)
def test_fit_line_rejects_missing_unknown_or_duplicate_evidence_ids(
    evidence_ids: list[str],
) -> None:
    luna = load_annotate_module()
    invalid = structured_annotation(
        "4377864561",
        fit_line_evidence_ids=evidence_ids,
    )
    runner = SequenceRunner(
        {"status": "ok", "data": invalid},
        {"status": "ok", "data": invalid},
    )

    result = luna.annotate(posting("direct"), runner=runner, profile_path=PROFILE_PATH)

    assert result == luna.INVALID_ANNOTATION


def test_fit_line_accepts_genuine_mcp_claim_with_genuine_profile_evidence(
    tmp_path: Path,
) -> None:
    luna = load_annotate_module()
    profile_path = tmp_path / "profile.yaml"
    write_safe_contract(profile_path, safe_projection())
    valid = structured_annotation(
        "4377864561",
        fit_line="Strong MCP infrastructure evidence matches the role.",
        fit_line_evidence_ids=["posting:4377864561", "brainlayer"],
    )

    result = luna.annotate(
        posting("direct"),
        runner=SequenceRunner({"status": "ok", "data": valid}),
        profile_path=profile_path,
    )

    assert result is not None
    assert result["luna_status"] == "ok"
    assert result["fit_line_evidence_ids"] == [
        "posting:4377864561",
        "brainlayer",
    ]


def test_posting_only_reason_allows_built_as_a_public_posting_fact() -> None:
    luna = load_annotate_module()
    fixture = json.loads(CALIBRATION_PATH.read_text(encoding="utf-8"))
    harmony = fixture["cases"][0]["posting"]
    valid = structured_annotation(
        "4459009700",
        fit_score=91,
        fit_tier="strong",
    )
    valid["reasons"][3]["detail"] = (
        "Harmony is built inside monday.com, so the named company is the direct employer."
    )

    result = luna.annotate(
        harmony,
        runner=SequenceRunner(
            {"status": "ok", "data": valid},
            {"status": "ok", "data": valid},
        ),
        profile_path=PROFILE_PATH,
    )

    assert result is not None
    assert result["luna_status"] == "ok"


def test_invalid_annotation_results_do_not_share_mutable_reason_lists() -> None:
    luna = load_annotate_module()
    malformed = {"status": "ok", "data": {"bad": "shape"}}

    first = luna.annotate(
        posting("direct"),
        runner=SequenceRunner(malformed, malformed),
        profile_path=PROFILE_PATH,
    )
    first["reasons"].append({"mutated": True})
    second = luna.annotate(
        posting("direct"),
        runner=SequenceRunner(malformed, malformed),
        profile_path=PROFILE_PATH,
    )

    assert second["reasons"] == []
    assert luna.INVALID_ANNOTATION["reasons"] == []
    assert first["reasons"] is not second["reasons"]


def test_explicit_human_verdict_cannot_be_overridden() -> None:
    luna = load_annotate_module()
    applied = posting("direct") | {"human_verdict": "applied"}
    conflicting = structured_annotation(
        "4377864561", fit_score=20, fit_tier="weak", recommendation="skip"
    )
    runner = SequenceRunner(
        {"status": "ok", "data": conflicting},
        {"status": "ok", "data": conflicting},
    )

    result = luna.annotate(applied, runner=runner, profile_path=PROFILE_PATH)

    assert result == luna.INVALID_ANNOTATION


def test_calibration_fixture_preserves_anonymous_reviewed_labels_without_private_data() -> (
    None
):
    fixture_text = CALIBRATION_PATH.read_text(encoding="utf-8")
    fixture = json.loads(fixture_text)
    cases = fixture["cases"]

    assert fixture["fixture_schema_version"] == 2
    assert fixture["snapshot"] == {
        "snapshot_id": "anonymous-2026-08-26-reviewed-current-source",
        "snapshot_version": 2,
        "source_kind": "reviewed_current_source",
        "source_label": "Anonymous reviewed current-source snapshot",
        "exported_at": "2026-08-26T15:42:51+03:00",
        "reviewed_at": "2026-08-26T15:42:51+03:00",
        "source_checksum": "sha256:3fff422d1adeca85a8f2efde90b5c0b1030fe2eef07b2a2be72db9d34392cdff",
        "snapshot_checksum": fixture["snapshot"]["snapshot_checksum"],
        "supabase_export_verified": False,
        "provenance_status": "blocked",
        "provenance_blocker": (
            "No verified Supabase export receipt or durable Supabase decision IDs "
            "were available."
        ),
    }
    canonical_cases = json.dumps(
        cases,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    assert fixture["snapshot"]["snapshot_checksum"] == (
        f"sha256:{hashlib.sha256(canonical_cases).hexdigest()}"
    )
    assert [
        (
            case["posting"]["id"],
            case["human_verdict"],
            case["human_rank"],
            case["decision_basis"],
            case["pair_eligible"],
        )
        for case in cases
    ] == [
        ("4459009700", "applied", 1, "fit", True),
        ("4457669002", "applied", 2, "fit", True),
        ("4457655885", "skip", None, "workflow_override", False),
    ]
    assert cases[0]["posting"]["title"] == "Software Engineer (Harmony)"
    assert cases[1]["posting"]["title"].endswith("Remote/Europe")
    assert cases[2]["posting"]["title"].endswith("Remote/US")
    assert cases[1]["posting"]["id"] != cases[2]["posting"]["id"]
    assert all(case["source_decision_id"] is None for case in cases)
    assert len({case["source_record_key"] for case in cases}) == 3
    assert all(len(case["posting"]["jd_text"]) >= 1000 for case in cases)
    for forbidden in (
        "PRIVATE_NAME_SENTINEL",
        "/Users/",
        "connector",
        "raw_private_note",
        "PRIVATE_RECRUITER_NOTE",
    ):
        assert forbidden not in fixture_text


def test_calibration_reports_exact_pairwise_agreements_and_disagreements() -> None:
    luna = load_annotate_module()
    fixture = json.loads(CALIBRATION_PATH.read_text(encoding="utf-8"))
    runner = SequenceRunner(
        {
            "status": "ok",
            "data": structured_annotation(
                "4459009700", fit_score=91, fit_tier="strong"
            ),
        },
        {
            "status": "ok",
            "data": structured_annotation("4457669002", fit_score=67, fit_tier="good"),
        },
        {
            "status": "ok",
            "data": structured_annotation("4457655885", fit_score=72, fit_tier="good"),
        },
    )

    report = luna.calibrate(fixture, runner=runner, profile_path=PROFILE_PATH)

    assert report["case_count"] == 3
    assert report["eligible_case_count"] == 2
    assert report["excluded_case_count"] == 1
    assert report["pair_count"] == 1
    assert report["eligible_applied_case_count"] == 2
    assert report["eligible_fit_mismatch_skip_count"] == 0
    assert report["applicable_pair_count"] == 0
    assert report["available_applicable_pair_count"] == 0
    assert report["agreement_count"] == 1
    assert report["disagreement_count"] == 0
    assert report["unavailable_pair_count"] == 0
    assert report["provisional"] is True
    assert report["spec_compliant"] is False
    assert report["provenance"] == fixture["snapshot"]
    assert report["blocked_requirements"] == [
        "supabase_export_unverified",
        "durable_decision_ids_unavailable",
        "verified_fit_mismatch_skip_unavailable",
        "applied_vs_fit_mismatch_pair_unavailable",
        "available_applied_vs_fit_mismatch_pair_unavailable",
    ]
    assert [
        (pair["expected_higher"], pair["expected_lower"], pair["outcome"])
        for pair in report["pairs"]
    ] == [
        ("4459009700", "4457669002", "agreement"),
    ]
    assert report["pairs"][0]["comparison_basis"] == "fit_rank"
    assert report["pairs"][0]["applicable_to_spec"] is False
    assert report["excluded_cases"] == [
        {
            "posting_id": "4457655885",
            "decision_basis": "workflow_override",
            "reason": "pair_eligible_false",
        }
    ]
    assert all("human_verdict" not in prompt for prompt, _schema in runner.calls)
    assert all(
        "explicit_human_recommendation" not in prompt
        for prompt, _schema in runner.calls
    )


def test_calibration_spec_compliance_requires_available_applied_over_fit_skip_pairs() -> (
    None
):
    luna = load_annotate_module()
    fixture = verified_calibration_fixture()
    runner = SequenceRunner(
        {
            "status": "ok",
            "data": structured_annotation(
                "4459009700", fit_score=91, fit_tier="strong"
            ),
        },
        {
            "status": "ok",
            "data": structured_annotation("4457669002", fit_score=67, fit_tier="good"),
        },
        {
            "status": "ok",
            "data": structured_annotation("4457655885", fit_score=72, fit_tier="good"),
        },
        {
            "status": "ok",
            "data": structured_annotation(
                "synthetic-fit-skip",
                fit_score=12,
                fit_tier="weak",
                recommendation="skip",
                fit_line=(
                    "Weak fit — embedded C++, semiconductor firmware, and ten years "
                    "are outside the profile."
                ),
            ),
        },
    )

    report = luna.calibrate(fixture, runner=runner, profile_path=PROFILE_PATH)

    assert report["eligible_applied_case_count"] == 2
    assert report["eligible_fit_mismatch_skip_count"] == 1
    assert report["applicable_pair_count"] == 2
    assert report["available_applicable_pair_count"] == 2
    assert report["blocked_requirements"] == []
    assert report["provisional"] is False
    assert report["spec_compliant"] is True
    assert [
        (
            pair["expected_higher"],
            pair["expected_lower"],
            pair["comparison_basis"],
            pair["applicable_to_spec"],
            pair["outcome"],
        )
        for pair in report["pairs"]
    ] == [
        ("4459009700", "4457669002", "fit_rank", False, "agreement"),
        (
            "4459009700",
            "synthetic-fit-skip",
            "applied_over_fit_mismatch_skip",
            True,
            "agreement",
        ),
        (
            "4457669002",
            "synthetic-fit-skip",
            "applied_over_fit_mismatch_skip",
            True,
            "agreement",
        ),
    ]


def test_calibration_zero_pairs_never_reports_spec_compliant() -> None:
    luna = load_annotate_module()
    fixture = verified_calibration_fixture()
    fixture["cases"] = [fixture["cases"][0]]
    refresh_calibration_checksum(fixture)

    report = luna.calibrate(
        fixture,
        runner=SequenceRunner(
            {
                "status": "ok",
                "data": structured_annotation(
                    "4459009700", fit_score=91, fit_tier="strong"
                ),
            }
        ),
        profile_path=PROFILE_PATH,
    )

    assert report["pair_count"] == 0
    assert report["applicable_pair_count"] == 0
    assert report["available_applicable_pair_count"] == 0
    assert report["spec_compliant"] is False
    assert report["blocked_requirements"] == [
        "verified_fit_mismatch_skip_unavailable",
        "applied_vs_fit_mismatch_pair_unavailable",
        "available_applied_vs_fit_mismatch_pair_unavailable",
    ]


def test_calibration_unavailable_applied_skip_pairs_never_report_compliant() -> None:
    luna = load_annotate_module()
    fixture = verified_calibration_fixture()
    runner = SequenceRunner(
        {
            "status": "ok",
            "data": structured_annotation(
                "4459009700", fit_score=91, fit_tier="strong"
            ),
        },
        {
            "status": "ok",
            "data": structured_annotation("4457669002", fit_score=67, fit_tier="good"),
        },
        {
            "status": "ok",
            "data": structured_annotation("4457655885", fit_score=72, fit_tier="good"),
        },
        {"status": "error", "exit_code": 1},
        {"status": "error", "exit_code": 1},
    )

    report = luna.calibrate(fixture, runner=runner, profile_path=PROFILE_PATH)

    assert report["pair_count"] == 3
    assert report["applicable_pair_count"] == 2
    assert report["available_applicable_pair_count"] == 0
    assert report["spec_compliant"] is False
    assert report["blocked_requirements"] == [
        "available_applied_vs_fit_mismatch_pair_unavailable"
    ]
    assert [
        pair["outcome"] for pair in report["pairs"] if pair["applicable_to_spec"]
    ] == ["unavailable", "unavailable"]


def test_calibration_rejects_checksum_or_pair_eligibility_confound() -> None:
    luna = load_annotate_module()
    fixture = json.loads(CALIBRATION_PATH.read_text(encoding="utf-8"))

    bad_checksum = copy.deepcopy(fixture)
    bad_checksum["snapshot"]["snapshot_checksum"] = f"sha256:{'0' * 64}"
    with pytest.raises(ValueError, match="snapshot checksum"):
        luna.calibrate(bad_checksum, runner=SequenceRunner(), profile_path=PROFILE_PATH)

    workflow_as_fit = copy.deepcopy(fixture)
    workflow_as_fit["cases"][2]["pair_eligible"] = True
    workflow_as_fit["cases"][2]["human_rank"] = 3
    canonical_cases = json.dumps(
        workflow_as_fit["cases"],
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    workflow_as_fit["snapshot"]["snapshot_checksum"] = (
        f"sha256:{hashlib.sha256(canonical_cases).hexdigest()}"
    )
    with pytest.raises(ValueError, match="workflow override"):
        luna.calibrate(
            workflow_as_fit,
            runner=SequenceRunner(),
            profile_path=PROFILE_PATH,
        )


def test_unverified_supabase_provenance_cannot_claim_durable_decision_ids() -> None:
    luna = load_annotate_module()
    fixture = json.loads(CALIBRATION_PATH.read_text(encoding="utf-8"))
    fixture["cases"][0]["source_decision_id"] = "invented-supabase-decision-id"
    canonical_cases = json.dumps(
        fixture["cases"],
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    fixture["snapshot"]["snapshot_checksum"] = (
        f"sha256:{hashlib.sha256(canonical_cases).hexdigest()}"
    )

    with pytest.raises(ValueError, match="unverified Supabase provenance"):
        luna.calibrate(fixture, runner=SequenceRunner(), profile_path=PROFILE_PATH)


def test_operational_failure_never_raises_into_caller() -> None:
    luna = load_annotate_module()
    runner = SequenceRunner(RuntimeError("cursor-agent unavailable"))

    assert (
        luna.annotate(posting("direct"), runner=runner, profile_path=PROFILE_PATH)
        is None
    )


def test_subscription_runner_invokes_luna_through_codex_exec(monkeypatch) -> None:
    luna = load_annotate_module()
    calls: list[tuple[list[str], str, dict[str, object]]] = []

    monkeypatch.setattr(luna, "_discover_codex", lambda: "/test/bin/codex")
    monkeypatch.setattr(luna, "_verify_codex_version", lambda _codex: None)
    monkeypatch.setattr(luna, "_subscription_auth_path", lambda: PROFILE_PATH)
    monkeypatch.setenv("JOB_RADAR_PRIVATE_SENTINEL", "must-not-reach-runner")

    # The stub mirrors subprocess.run's required keyword name.
    def fake_run(command, *, input, **kwargs):  # skipcq: PYL-W0622
        calls.append((command, input, kwargs))
        isolated_home = Path(kwargs["env"]["CODEX_HOME"])
        assert (isolated_home / "auth.json").is_symlink()
        assert (isolated_home / "auth.json").resolve() == PROFILE_PATH.resolve()
        output_path = Path(command[command.index("--output-last-message") + 1])
        output_path.write_text(
            json.dumps(
                structured_annotation(
                    "subscription-example",
                    seniority_real=True,
                    fit_score=82,
                    fit_tier="strong",
                    recommendation="apply",
                    fit_line="Strong full-stack fit.",
                )
            ),
            encoding="utf-8",
        )
        return SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr(luna.subprocess, "run", fake_run)

    result = luna._subscription_runner("annotate me", luna.LUNA_SCHEMA)

    command, prompt, run_options = calls[0]
    assert command[:2] == ["/test/bin/codex", "exec"]
    assert command[command.index("-m") + 1] == "gpt-5.6-luna"
    assert luna.LUNA_REASONING_EFFORT == "xhigh"
    assert 'model_reasoning_effort="xhigh"' in command
    assert "--strict-config" in command
    assert "--ignore-user-config" in command
    assert "--ignore-rules" in command
    disabled_features = {
        command[index + 1]
        for index, argument in enumerate(command[:-1])
        if argument == "--disable"
    }
    assert disabled_features == set(luna.CODEX_DISABLED_FEATURES)
    assert {"shell_tool", "code_mode_host", "computer_use", "view_image"} <= (
        disabled_features
    )
    assert command[command.index("--sandbox") + 1] == "read-only"
    isolated_root = command[command.index("-C") + 1]
    assert run_options["cwd"] == Path(isolated_root)
    assert Path(isolated_root) != luna.REPO_ROOT
    isolated_home = Path(run_options["env"]["CODEX_HOME"])
    assert isolated_home.parent == Path(isolated_root).parent
    assert isolated_home != Path(isolated_root)
    assert run_options["env"]["HOME"] == str(isolated_home)
    assert run_options["env"] == luna._isolated_codex_environment(isolated_home)
    assert "JOB_RADAR_PRIVATE_SENTINEL" not in run_options["env"]
    assert "--output-schema" in command
    assert "--output-last-message" in command
    assert command[-1] == "-"
    assert prompt == "annotate me"
    assert result == {
        "status": "ok",
        "exit_code": 0,
        "data": {
            "employer_type": "direct",
            "seniority_real": True,
            "fit_score": 82,
            "fit_tier": "strong",
            "recommendation": "apply",
            "reasons": structured_annotation("subscription-example")["reasons"],
            "fit_line": "Strong full-stack fit.",
            "fit_line_evidence_ids": [
                "posting:subscription-example",
                "example-project",
            ],
        },
    }


def test_subscription_auth_path_resolves_relative_codex_home(
    monkeypatch, tmp_path
) -> None:
    luna = load_annotate_module()
    relative_home = Path("relative-codex-home")
    auth_path = tmp_path / relative_home / "auth.json"
    auth_path.parent.mkdir()
    auth_path.write_text("test-only-placeholder", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CODEX_HOME", str(relative_home))

    resolved = luna._subscription_auth_path()

    assert resolved == auth_path.resolve()
    assert resolved.is_absolute()


def test_subscription_runner_rejects_unverified_codex_version(monkeypatch) -> None:
    luna = load_annotate_module()
    monkeypatch.setattr(luna, "_discover_codex", lambda: "/test/bin/codex")
    monkeypatch.setattr(
        luna.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=0,
            stdout="codex-cli 0.154.0\n",
            stderr="",
        ),
    )

    with pytest.raises(RuntimeError, match="requires codex-cli 0.153.4"):
        luna._subscription_runner("annotate me", luna.LUNA_SCHEMA)


def test_subscription_runner_fails_closed_when_strict_config_is_rejected(
    monkeypatch,
) -> None:
    luna = load_annotate_module()
    monkeypatch.setattr(luna, "_discover_codex", lambda: "/test/bin/codex")
    monkeypatch.setattr(luna, "_verify_codex_version", lambda _codex: None)
    monkeypatch.setattr(luna, "_subscription_auth_path", lambda: PROFILE_PATH)
    monkeypatch.setattr(
        luna.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=1,
            stderr="Error: Unknown feature flag: shell_tool",
        ),
    )

    assert luna._subscription_runner("annotate me", luna.LUNA_SCHEMA) == {
        "status": "error",
        "exit_code": 1,
        "stderr": "Error: Unknown feature flag: shell_tool",
    }
