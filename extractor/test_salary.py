"""Numeric salary policy using synthetic postings with triage salary wording."""

from copy import deepcopy

import pytest

from extractor import core
from extractor.payload import build_payload
from extractor.test_core import facts, posting, runner_for, RAW_JD
from scraper.brain_contract import BrainValidationError

TRIAGE_SALARIES = [
    "highly competitive salaries",
    "highly competitive salaries",
    "highly competitive salaries",
    "highly competitive salaries",
    "highly competitive salaries",
    "competitive salaries",
    "competitive salaries",
    "highly competitive salaries",
    "competitive salaries",
    "highly competitive salaries",
    "highly competitive salaries",
    "highly competitive salaries",
    "competitive salaries",
    "competitive salaries",
    "highly competitive salaries",
    "competitive salaries",
    "competitive salaries",
    "competitive salaries",
    "highly competitive salaries",
    "competitive salaries",
    "highly competitive salaries",
]


@pytest.mark.parametrize(
    "salary",
    TRIAGE_SALARIES
    + [
        "competitive salary",
        "equity + benefits",
        "DOE",
        "competitive salary with 25 days PTO",
        "3+ years of experience",
        "401(k) and benefits",
        "10% equity",
        "2026 compensation review",
        "401k", "401(k)", "competitive salary + 401k", "401k matching",
        "2026", "24/7", "2 years", "100% remote", "3 days a week",
        "raised $10M", "Series B funding of $50M",
        "Competitive salary. Raised $10M", "Competitive salary; Series B funding of $50M",
        "180000", "35K-45K", "120,000 - 150,000", "78,100 to 88,950",
        "401k retirement plan", "salary includes 401k matching",
        "pay 2 years", "salary 100% remote", "pay 3 days a week",
        "salary 120k retirement-plan benefit",
        "Engineer Level One 90000 to 120000 requires a Bachelor of Science degree\n\n"
        "Engineer Level Two 110000 to 140000 requires BS plus 2 years or MS plus 0 years\n\n"
        "Staff Engineer 130000 to 160000 requires BS plus 5 years MS plus 3 years or PhD",
    ],
)
def test_boilerplate_is_preserved_only_as_raw_remark(salary):
    candidate = facts()
    candidate["salary"] = {"value": salary, "evidence_quote": salary}
    raw_jd = RAW_JD + "\n" + salary
    result = core.extract_posting(posting(raw_jd), {}, runner=runner_for(candidate))
    assert result["facts"]["salary"] == {"value": None, "evidence_quote": None}
    assert result["facts"]["salary_remark"] == salary
    assert build_payload(result, raw_jd).facts == result["facts"]
    assert candidate["salary"]["value"] == salary


@pytest.mark.parametrize(
    "salary",
    [
        "$180,000 - $250,000 USD annually",
        "₪35K-45K/month",
        "120k-150k EUR",
        "$50/hour",
        "50 per hour",
        "שכר 35000 בחודש", '35,000 ש״ח לחודש', "35,000 שקלים בחודש",
        "שכר 25,000-30,000 ₪", "עד 35 אלף", "₪30K",
        "up to 180000", "up to $200k", "up to 150,000 EUR",
        "salary 120k", "pay 120K", "compensation 120 thousand",
        "שכר 35 אלף", "120k per year", "35k per month", "50 hourly",
        "salary $150k plus 401k matching", "Salary: 120,000", "שכר: 35000",
        "Salary $120k. Raised $10M",
    ],
)
def test_numeric_compensation_preserves_salary_contract(salary):
    candidate = facts()
    candidate["salary"] = {"value": salary, "evidence_quote": salary}
    raw_jd = RAW_JD + "\n" + salary
    result = core.extract_posting(posting(raw_jd), {}, runner=runner_for(candidate))
    assert result["facts"] == candidate
    assert build_payload(result, raw_jd).facts == candidate


def test_boilerplate_still_requires_exact_source_support():
    candidate = facts()
    candidate["salary"] = {
        "value": "competitive salary",
        "evidence_quote": "competitive salary",
    }
    with pytest.raises(BrainValidationError):
        core.extract_posting(posting(), {}, runner=runner_for(candidate))


def test_remark_cannot_bypass_evidence_validation():
    from extractor.test_payload import extraction

    candidate = deepcopy(facts())
    candidate["salary"] = {"value": None, "evidence_quote": None}
    candidate["salary_remark"] = "invented boilerplate"
    with pytest.raises(BrainValidationError):
        build_payload(extraction(RAW_JD, candidate), RAW_JD)


def test_validator_rejects_nonnumeric_salary_without_postprocessing():
    from extractor.evidence import validate_facts

    candidate = facts()
    candidate["salary"] = {
        "value": "competitive salary",
        "evidence_quote": "competitive salary",
    }
    with pytest.raises(BrainValidationError, match="numeric compensation"):
        validate_facts(candidate, RAW_JD + " competitive salary")


def test_payload_normalizes_legacy_salary_without_mutating_input():
    from extractor.test_payload import extraction

    raw_jd = RAW_JD + " competitive salary"
    candidate = facts()
    candidate["salary"] = {
        "value": "competitive salary",
        "evidence_quote": "competitive salary",
    }
    original = extraction(raw_jd, candidate)
    saved = deepcopy(original)
    payload = build_payload(original, raw_jd)
    assert payload.facts["salary"] == {"value": None, "evidence_quote": None}
    assert payload.facts["salary_remark"] == "competitive salary"
    assert original == saved
