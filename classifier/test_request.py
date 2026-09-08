from __future__ import annotations

import json
from pathlib import Path

import pytest

from classifier import request as scoring_request
from scraper.annotate import (
    FACTOR_BASES,
    PROFILE_EVIDENCE_IDS,
    REASON_FACTORS,
    WITHHELD_ABSTENTION_DETAIL,
    WITHHELD_PROFILE_EVIDENCE_IDS,
    _validated_annotation,
)
from scraper.brain import BrainResult, BrainValidationError
from scraper.test_annotate import safe_projection, structured_annotation


HERE = Path(__file__).parent
REJECTED_PATH = HERE / "fixtures" / "prompt-contract-rejected.json"
SYNTHETIC_GLOBAL_LITERAL = "synthetic-never-specialty"


def request_inputs():
    profile = safe_projection()
    profile["candidate"]["professional_depth"] = {
        "TypeScript": ["hands-on"],
    }
    posting = {
        "id": "4459009700",
        "title": "Software Engineer (Harmony)",
        "company": "monday.com",
        "location": "Tel Aviv",
        "jd_text": "Build public TypeScript backend voice services. " * 10,
    }
    history = [{
        "evidence_id": "application-history:history-1",
        "company": "Prior Public Company",
        "role": None,
        "application_date": None,
        "outcome": None,
    }]
    return posting, profile, history


def build_test_request():
    return scoring_request.build_request(*request_inputs())


def valid_wire_response() -> dict[str, object]:
    response = structured_annotation("4459009700")
    response.pop("fit_tier")
    response.pop("recommendation")
    posting_id = "posting:4459009700"
    keyed_reasons = {}
    for reason in response["reasons"]:
        reason = dict(reason)
        if reason["factor"] == "employer_type":
            reason.pop("evidence_ids")
        else:
            reason["evidence_ids"] = [
                evidence_id for evidence_id in reason["evidence_ids"]
                if evidence_id != posting_id
            ][:1]
        keyed_reasons[reason["factor"]] = reason
    response["reasons"] = keyed_reasons
    response["fit_line_evidence_ids"] = ["example-project"]
    return response


def test_retained_native_rejection_fails_wire_schema() -> None:
    rejected = json.loads(REJECTED_PATH.read_text(encoding="utf-8"))

    with pytest.raises(BrainValidationError):
        BrainResult(rejected, "ollama", "qwen-test", request=build_test_request())


@pytest.mark.parametrize("case", ["wrong-factor", "withheld-slot", "fabricated-id"])
def test_wire_schema_rejects_wrong_slot_or_nonliteral_evidence(case: str) -> None:
    response = valid_wire_response()
    if case == "wrong-factor":
        response["reasons"]["product_role_match"]["factor"] = "preferences"
    elif case == "withheld-slot":
        response["reasons"]["product_role_match"]["evidence_ids"] = [
            "profile:preferences",
        ]
    else:
        response["reasons"]["stack_domain_evidence"]["evidence_ids"] = [
            "profile:example-workflow",
        ]

    with pytest.raises(BrainValidationError):
        BrainResult(response, "ollama", "qwen-test", request=build_test_request())


def test_valid_wire_normalizes_exactly_then_passes_semantic_validation() -> None:
    posting, profile, history = request_inputs()
    request = scoring_request.build_request(posting, profile, history)
    result = BrainResult(
        valid_wire_response(), "ollama", "qwen-test", request=request
    )

    normalized = scoring_request.normalize_response(
        result.data,
        posting_evidence_id="posting:4459009700",
        expected_recommendation=None,
    )
    allowed = (
        {"posting:4459009700"}
        | PROFILE_EVIDENCE_IDS
        | {str(signal["evidence_id"]) for signal in profile["fit_signals"]}
        | {str(row["evidence_id"]) for row in history}
    )
    validated = _validated_annotation(
        normalized,
        profile=profile,
        allowed_evidence_ids=allowed,
        posting_evidence_id="posting:4459009700",
        expected_recommendation=None,
    )

    assert validated is not None
    assert [reason["factor"] for reason in normalized["reasons"]] == REASON_FACTORS
    assert normalized["fit_tier"] == "good"
    assert normalized["recommendation"] == "apply"


def test_request_schema_and_prompt_match_the_constrained_wire_contract() -> None:
    request = build_test_request()
    schema = request.output_schema
    reasons = schema["properties"]["reasons"]

    assert reasons["type"] == "object"
    assert reasons["required"] == REASON_FACTORS
    assert set(reasons["properties"]) == set(REASON_FACTORS)
    assert "fit_tier" not in schema["properties"]
    assert "recommendation" not in schema["properties"]
    for factor in REASON_FACTORS:
        slot = reasons["properties"][factor]
        assert slot["properties"]["factor"]["enum"] == [factor]
        assert slot["properties"]["basis"]["enum"] == [FACTOR_BASES[factor]]
        if factor == "employer_type":
            assert "evidence_ids" not in slot["properties"]
        else:
            evidence = slot["properties"]["evidence_ids"]
            assert evidence["minItems"] == evidence["maxItems"] == 1
    preference = reasons["properties"]["preferences"]["properties"]
    assert preference["assessment"]["enum"] == ["unknown"]
    assert preference["detail"]["enum"] == [WITHHELD_ABSTENTION_DETAIL]
    preference_ids = set(preference["evidence_ids"]["items"]["enum"])
    assert preference_ids == {
        *WITHHELD_PROFILE_EVIDENCE_IDS,
    }
    normal_ids = set(
        reasons["properties"]["product_role_match"]["properties"]
        ["evidence_ids"]["items"]["enum"]
    )
    fit_line_ids = set(
        schema["properties"]["fit_line_evidence_ids"]["items"]["enum"]
    )
    assert not normal_ids & WITHHELD_PROFILE_EVIDENCE_IDS
    assert "posting:4459009700" not in normal_ids
    assert not fit_line_ids & WITHHELD_PROFILE_EVIDENCE_IDS
    assert "posting:4459009700" not in fit_line_ids
    assert "reasons is a closed object keyed" in request.prompt
    assert "Copy every evidence ID byte-for-byte" in request.prompt
    assert "exactly one candidate evidence ID" in request.prompt
    assert "Local score policy: 60-100=apply, 40-59=review, 0-39=skip" in request.prompt
    assert "your recommendation must match" not in request.prompt
    assert "applied locally after model output" in request.prompt
    assert "If fit_tier is weak" not in request.prompt
    assert "If fit_score is below 40" in request.prompt
    assert WITHHELD_ABSTENTION_DETAIL in request.prompt
    assert "synthetic-project" not in request.prompt


def test_request_keeps_global_literals_local_and_requires_neutral_wording() -> None:
    posting, profile, history = request_inputs()
    global_literals = profile["constraints"]["global_never_claims"]
    global_literals.append(SYNTHETIC_GLOBAL_LITERAL)

    prompt = scoring_request.build_request(posting, profile, history).prompt
    assert SYNTHETIC_GLOBAL_LITERAL not in prompt
    assert (
        "describe only whether the named employer is hiring directly or through an agency"
        in prompt
    )
    assert "do not repeat the posting's specialty or title" in prompt
    assert "cite concrete verified candidate work" in prompt
    assert "For non-preferences comparison reasons and fit_line" in prompt
    assert "The preferences key is the only withheld-evidence slot" in prompt
    assert WITHHELD_ABSTENTION_DETAIL in prompt
    assert 'posting specialty labels only as "this role"' in prompt
    assert "including in negative comparisons" in prompt


@pytest.mark.parametrize(
    ("score", "tier", "recommendation"),
    [
        (0, "weak", "skip"), (39, "weak", "skip"),
        (40, "stretch", "review"), (59, "stretch", "review"),
        (60, "good", "apply"), (79, "good", "apply"),
        (80, "strong", "apply"), (100, "strong", "apply"),
    ],
)
def test_normalization_derives_tier_and_recommendation_from_score(
    score: int, tier: str, recommendation: str,
) -> None:
    response = valid_wire_response()
    response["fit_score"] = score

    normalized = scoring_request.normalize_response(
        response,
        posting_evidence_id="posting:4459009700",
        expected_recommendation=None,
    )

    assert normalized["fit_tier"] == tier
    assert normalized["recommendation"] == recommendation


@pytest.mark.parametrize("score", [-1, 101, True, 1.5, "60"])
def test_normalization_rejects_invalid_or_noninteger_scores(score: object) -> None:
    response = valid_wire_response()
    response["fit_score"] = score
    with pytest.raises(ValueError, match="fit score"):
        scoring_request.normalize_response(
            response,
            posting_evidence_id="posting:4459009700",
            expected_recommendation=None,
        )


def test_normalization_preserves_explicit_human_recommendation() -> None:
    response = valid_wire_response()
    response["fit_score"] = 10

    normalized = scoring_request.normalize_response(
        response,
        posting_evidence_id="posting:4459009700",
        expected_recommendation="referral",
    )

    assert normalized["fit_tier"] == "weak"
    assert normalized["recommendation"] == "referral"


def test_normalization_inserts_posting_id_once_for_every_canonical_claim() -> None:
    response = valid_wire_response()
    normalized = scoring_request.normalize_response(
        response,
        posting_evidence_id="posting:4459009700",
        expected_recommendation=None,
    )

    for reason in normalized["reasons"]:
        assert reason["evidence_ids"].count("posting:4459009700") == 1
    assert normalized["fit_line_evidence_ids"].count("posting:4459009700") == 1


def test_wire_rejects_pooled_or_duplicate_candidate_claims() -> None:
    request = build_test_request()
    for evidence_ids in (
        ["brainlayer", "voice-agent-tool-calling"],
        ["example-project", "example-project"],
    ):
        response = valid_wire_response()
        response["reasons"]["product_role_match"]["evidence_ids"] = evidence_ids
        with pytest.raises(BrainValidationError):
            BrainResult(response, "ollama", "qwen-test", request=request)


def test_unchanged_validator_rejects_pooled_mcp_claim_and_accepts_its_source() -> None:
    posting_id = "posting:4459009700"
    profile = safe_projection()
    allowed = {posting_id} | PROFILE_EVIDENCE_IDS | {
        str(signal["evidence_id"]) for signal in profile["fit_signals"]
    }
    pooled = structured_annotation("4459009700")
    product_reason = next(
        reason for reason in pooled["reasons"]
        if reason["factor"] == "product_role_match"
    )
    product_reason["detail"] = "MCP delivery is relevant to this product role."
    product_reason["evidence_ids"] = [
        posting_id, "brainlayer", "voice-agent-tool-calling",
    ]
    single_source = json.loads(json.dumps(pooled))
    single_source["reasons"][0]["evidence_ids"] = [posting_id, "brainlayer"]

    assert _validated_annotation(
        pooled, profile=profile, allowed_evidence_ids=allowed,
        posting_evidence_id=posting_id, expected_recommendation=None,
    ) is None
    assert _validated_annotation(
        single_source, profile=profile, allowed_evidence_ids=allowed,
        posting_evidence_id=posting_id, expected_recommendation=None,
    ) is not None


def test_request_drops_unprojected_history_fields() -> None:
    posting, profile, history = request_inputs()
    history[0]["internal_decision"] = "PRIVATE_HISTORY_SENTINEL"

    request = scoring_request.build_request(posting, profile, history)

    assert "PRIVATE_HISTORY_SENTINEL" not in request.prompt
    assert "internal_decision" not in request.prompt
    assert "Prior Public Company" in request.prompt
