"""Numeric salary policy using synthetic postings with triage salary wording."""

from copy import deepcopy

import pytest

from extractor import core
from extractor.payload import build_payload
from extractor.test_core import facts, posting, runner_for, RAW_JD
from scraper.brain_contract import BrainValidationError

# Shared extraction/SQL regression corpus from both round-2 reviews and the fix brief.
ROUND2_SALARY_CASES = [
    ("30 אלף שקל", True), ("30 אלף שקלים", True), ("30 אלף ₪", True),
    ("₪30 אלף", True), ("30 שקל", True), ("30 שקלים", True),
    ('30 ש"ח', True), ("30 ₪", True), ("30 K שקל", True),
    ("30 thousand שקל", True), ("₪30 thousand", True),
    ("salary raised to $150k", True), ("pay raised to $150k", True),
    ("compensation raised to $150k", True),
    ("up to 2026 graduates", False), ("up to 500 employees", False),
    ("up to 180000", True), ("up to $200k", True), ("up to 150,000 EUR", True),
    ("up to 2026", False), ("up to 500", False), ("up to 5000", False),
    ("up to 5000 salary", True), ("up to 500 K", True),
    ("up to 500 salary", True), ("pay up to 500", True),
    ("raised $10M", False), ("Series B funding of $50M", False),
    ("raised a seed round of $500k", False), ("funding from investors: $500k", False),
    ("funding of $500k", False), ("raised $2B", False),
    ("401(k) match up to 6%", False), ("$5k signing bonus", True),
    ("bonus of $5k", True), ("competitive, DOE", False), ("₪", False),
    ("25-30", False), ("€70.000", True), ("USD 120K-150K", True),
    ("$40/hr", True), ("2026 graduates", False), ("24/7 on-call", False),
    ("שכר 30 אלף שקל", True), ("עד 30 אלף שקל", True),
    ("salary 120k + 401(k) match up to 6%", True),
    ("401k", False), ("competitive salary + 401k", False), ("2026", False),
    ("שכר 35000 בחודש", True), ('35,000 ש״ח לחודש', True),
    ("35,000 שקלים בחודש", True), ("שכר 25,000-30,000 ₪", True),
    ("עד 35 אלף", True), ("₪30K", True),
    ("401(k)", False), ("401k matching", False),
    ("raised at a valuation of $500k", False), ("funding $10M", False),
    ("78,100 to 88,950", False),
    ("Engineer Level One 90000 to 120000 requires a Bachelor of Science degree\n\n"
     "Engineer Level Two 110000 to 140000 requires BS plus 2 years or MS plus 0 years\n\n"
     "Staff Engineer 130000 to 160000 requires BS plus 5 years MS plus 3 years or PhD", False),
]


# Round-3 funding regressions; reused by the real PostgreSQL persistence test.
ROUND3_SALARY_CASES = [
    ("raised €10M", False), ("raised £5 million", False),
    ('גייסנו 20 מיליון ש"ח', False), ("raised $500k", False),
    ("salary raised to $150k", True), ("base pay raised to €90k", True),
    ("pay raised to ₪40,000", True), ("base raised to £90k", True),
    ("שכר הועלה ל-₪40,000", True),
] + [
    (f"raised {currency}10{unit}", False)
    for currency in ("$", "€", "£", "₪", "USD ", "EUR ", "GBP ", "ILS ", 'ש"ח ')
    for unit in ("M", "B", " million", " billion", " מיליון")
] + [
    (f"גייסנו 20 מיליון {currency}", False)
    for currency in ("$", "€", "£", "₪", "USD", "EUR", "GBP", "ILS", 'ש"ח')
]


ROUND4_SALARY_CASES = [
    ("competitive salary, raised $10M", False),
    ("competitive salary, raised $10M in Series A", False),
    ("competitive salary, raised $500k", False),
    ("competitive salary, raised €10M", False),
    ("competitive pay and raised £5 million", False),
    ("hourly rate raised to $50/hour", True),
    ("rate raised to €50 per hour", True),
    ("hourly rate raised to $45/hr", True),
    ("we raised $10M and pay $150k base", True),
    ("OTE $200k, Series B $40M", True),
    ("salary $150k, funding $10M", True),
    ("funding $10M, salary $150k", True),
    ("salary raised to $150k in funding announcement", True),
    ("Series B $40M", False),
    ("seed $500k", False),
    ("round of $10M", False),
    ("investors contributed $10M", False),
    ("valuation $10M", False),
    ("$1M ARR", False),
    ("revenue $10M", False),
    ("wage raised to $50", True),
    ("rate 50/hr", True),
]


@pytest.mark.parametrize(
    "salary, numeric", ROUND2_SALARY_CASES + ROUND3_SALARY_CASES + ROUND4_SALARY_CASES,
)
def test_round2_salary_extraction_and_payload(salary, numeric):
    candidate = facts()
    candidate["salary"] = {"value": salary, "evidence_quote": salary}
    raw_jd = RAW_JD + "\n" + salary
    result = core.extract_posting(posting(raw_jd), {}, runner=runner_for(candidate))
    expected = deepcopy(candidate)
    if not numeric:
        expected["salary"] = {"value": None, "evidence_quote": None}
        expected["salary_remark"] = salary
    assert result["facts"] == expected
    assert build_payload(result, raw_jd).facts == expected
    assert candidate["salary"]["value"] == salary


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
