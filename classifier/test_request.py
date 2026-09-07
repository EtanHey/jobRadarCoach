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
    response["reasons"] = {
        reason["factor"]: reason for reason in response["reasons"]
    }
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
            "posting:4459009700",
            "profile:preferences",
        ]
    else:
        response["reasons"]["stack_domain_evidence"]["evidence_ids"] = [
            "posting:4459009700",
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

    normalized = scoring_request.normalize_response(result.data)
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


def test_request_schema_and_prompt_match_the_constrained_wire_contract() -> None:
    request = build_test_request()
    schema = request.output_schema
    reasons = schema["properties"]["reasons"]

    assert reasons["type"] == "object"
    assert reasons["required"] == REASON_FACTORS
    assert set(reasons["properties"]) == set(REASON_FACTORS)
    for factor in REASON_FACTORS:
        slot = reasons["properties"][factor]
        assert slot["properties"]["factor"]["enum"] == [factor]
        assert slot["properties"]["basis"]["enum"] == [FACTOR_BASES[factor]]
    preference = reasons["properties"]["preferences"]["properties"]
    assert preference["assessment"]["enum"] == ["unknown"]
    assert preference["detail"]["enum"] == [WITHHELD_ABSTENTION_DETAIL]
    preference_ids = set(preference["evidence_ids"]["items"]["enum"])
    assert preference_ids == {
        "posting:4459009700",
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
    assert not fit_line_ids & WITHHELD_PROFILE_EVIDENCE_IDS
    assert "reasons is a closed object keyed" in request.prompt
    assert "Copy every evidence ID byte-for-byte" in request.prompt
    assert WITHHELD_ABSTENTION_DETAIL in request.prompt
    assert "synthetic-project" not in request.prompt


def test_request_drops_unprojected_history_fields() -> None:
    posting, profile, history = request_inputs()
    history[0]["internal_decision"] = "PRIVATE_HISTORY_SENTINEL"

    request = scoring_request.build_request(posting, profile, history)

    assert "PRIVATE_HISTORY_SENTINEL" not in request.prompt
    assert "internal_decision" not in request.prompt
    assert "Prior Public Company" in request.prompt
