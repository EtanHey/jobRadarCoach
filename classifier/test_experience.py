"""Synthetic regressions for subject-scoped experience scoring inputs."""

import copy
import json

import pytest

from classifier import request
from classifier.test_core import SequenceBrain, posting, profile_snapshot, wire_annotation
from classifier import core
from scraper.test_annotate import safe_projection
from scraper.brain import BrainResult, BrainValidationError


def comparisons(jd, claims=()):
    from classifier.experience import compare_experience

    profile = safe_projection()
    profile["candidate"]["tenure_years"] = 3.7
    template = profile["fit_signals"][0]
    profile["fit_signals"] = [
        {**copy.deepcopy(template), "evidence_id": f"duration-{i}", "claim": claim}
        for i, claim in enumerate(claims)
    ]
    return compare_experience(jd, profile)


@pytest.mark.parametrize("jd", [
    "2+ years React",
    "3+ years of hands-on Angular development experience – Mandatory",
    "2+ years of hands-on experience developing LLM-based AI solutions – Mandatory",
    "3 years of backend development experience",
])
def test_overall_tenure_never_establishes_specialist_duration(jd):
    result = comparisons(jd)[0]
    assert result["candidate_years"] is None
    assert result["assessment"] == "unknown"
    assert result["subject_kind"] == "specialist"


@pytest.mark.parametrize(("claim", "expected", "assessment"), [
    ("2 years React", 2, "met"),
    ("1 year of React experience", 1, "below"),
    ("3 years of Angular experience", None, "unknown"),
    ("Built React applications", None, "unknown"),
    ("No 2 years React", None, "unknown"),
    ("2 years React or Angular", None, "unknown"),
    ("Less than 2 years React", None, "unknown"),
])
def test_only_explicit_matching_duration_claims_are_compared(claim, expected, assessment):
    result = comparisons("2+ years React", [claim])[0]
    assert result["candidate_years"] == expected
    assert result["assessment"] == assessment
    assert result["candidate_evidence_ids"] == ([] if expected is None else ["duration-0"])


def test_overlapping_projects_are_not_summed():
    result = comparisons("3 years React", ["2 years React", "2 years React"])[0]
    assert result["candidate_years"] == 2
    assert result["assessment"] == "below"


def test_requirement_range_uses_minimum_and_lower_bound_is_not_a_shortfall():
    assert comparisons("2-4 years React", ["3 years React"])[0]["assessment"] == "met"
    assert comparisons("3 years React", ["2+ years React"])[0]["assessment"] == "unknown"
    assert comparisons("3 years React", ["2-4 years React"])[0]["assessment"] == "unknown"


@pytest.mark.parametrize("jd", [
    "3+ years of professional software engineering experience",
    "3 years of software development experience",
])
def test_overall_requirement_can_use_overall_tenure(jd):
    result = comparisons(jd)[0]
    assert result["subject_kind"] == "overall"
    assert result["candidate_years"] == 3.7
    assert result["assessment"] == "met"
    assert result["candidate_evidence_ids"] == ["profile:tenure"]


def test_separate_overall_and_specialist_requirements():
    result = comparisons("3 years of software development experience; 2 years React")
    assert [row["assessment"] for row in result] == ["met", "unknown"]


@pytest.mark.parametrize("jd", [
    "2 years of experience",
    "2 years of software development experience with React",
    "2 years of experience in an unspecified specialty",
])
def test_ambiguous_subject_does_not_fall_back_to_total_tenure(jd):
    assert comparisons(jd)[0]["assessment"] == "unknown"


def test_unverified_duration_is_not_candidate_evidence():
    from classifier.experience import compare_experience

    profile = safe_projection()
    profile["fit_signals"][0].update(claim="3 years React", status="unverified")
    assert compare_experience("2 years React", profile)[0]["candidate_years"] is None


def test_unknown_specialist_tenure_constrains_real_scoring_request():
    snapshot = profile_snapshot()
    job = posting("Requirements: 2+ years React.\n" + "Build web applications. " * 15)
    response = wire_annotation(job["id"])
    response["reasons"]["seniority_gap"]["assessment"] = "unknown"
    runner = SequenceBrain(response)
    result = core.score_posting(snapshot, job, [], brain_runner=runner)
    assert result is not None
    sent = runner.calls[0][0]
    assert "Deterministic experience comparisons:" in sent.prompt
    payload = sent.prompt.split("Deterministic experience comparisons:\n")[1].split("\n")[0]
    assert json.loads(payload)[0]["candidate_years"] is None
    reason_schema = sent.output_schema["properties"]["reasons"]["properties"]["seniority_gap"]
    assert reason_schema["properties"]["assessment"]["enum"] == ["unknown"]
    response["reasons"]["seniority_gap"]["detail"] = reason_schema["properties"]["detail"]["enum"][0]
    BrainResult(response, "ollama", "test", request=sent)
    response["reasons"]["seniority_gap"]["assessment"] = "positive"
    with pytest.raises(BrainValidationError):
        BrainResult(response, "ollama", "test", request=sent)


def test_known_skill_duration_is_available_to_scoring():
    profile = safe_projection()
    profile["fit_signals"][0]["claim"] = "2 years React"
    sent = request.build_request({"id": "test", "jd_text": "2 years React"}, profile, [])
    schema = sent.output_schema["properties"]["reasons"]["properties"]["seniority_gap"]
    assert "positive" in schema["properties"]["assessment"]["enum"]
    assert schema["properties"]["evidence_ids"]["items"]["enum"] == ["example-project"]
    assert '"candidate_years": 2.0' in sent.prompt


def test_proven_specialist_shortfall_cannot_receive_a_positive_assessment():
    profile = safe_projection()
    profile["fit_signals"][0]["claim"] = "1 year React"
    sent = request.build_request({"id": "test", "jd_text": "2 years React"}, profile, [])
    schema = sent.output_schema["properties"]["reasons"]["properties"]["seniority_gap"]
    assert schema["properties"]["assessment"]["enum"] == ["mixed", "negative"]


def test_posting_without_years_keeps_existing_seniority_schema():
    sent = request.build_request({"id": "test", "jd_text": "Build React applications."}, safe_projection(), [])
    schema = sent.output_schema["properties"]["reasons"]["properties"]["seniority_gap"]
    assert schema["properties"]["assessment"]["enum"] == ["positive", "mixed", "negative", "unknown"]


def test_company_history_does_not_become_a_candidate_requirement():
    assert comparisons("Our company has 20 years of software development experience.") == []
    assert comparisons("We were founded 10 years ago.") == []
    assert comparisons("You have 2 years of React experience.")[0]["assessment"] == "unknown"
