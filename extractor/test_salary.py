"""Numeric salary policy using synthetic postings with triage salary wording."""

from copy import deepcopy

import pytest

from extractor import core
from extractor.payload import build_payload
from extractor.test_core import RAW_JD, facts, posting, runner_for
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
    (("Engineer Level One 90000 to 120000 requires a Bachelor of Science degree\n\n"
     "Engineer Level Two 110000 to 140000 requires BS plus 2 years or MS plus 0 years\n\n"
     "Staff Engineer 130000 to 160000 requires BS plus 5 years MS plus 3 years or PhD"), False),
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


# Preserve the historical corpora; only genuine competing governors demote pay.
CONSERVATIVE_SALARY_REMARKS = {
    "base raised to £90k": "Bare base before the amount does not establish pay ownership.",
    "salary raised to $150k in funding announcement":
        "Funding competes with the raised-pay construction in the same window.",
}
PRECISION_PREVIOUS_SALARY_CASES = [
    (value, numeric and value not in CONSERVATIVE_SALARY_REMARKS)
    for value, numeric in ROUND2_SALARY_CASES + ROUND3_SALARY_CASES + ROUND4_SALARY_CASES
]

# Every concrete probe in both round-5 reviews, including prose controls.
ROUND5_SALARY_CASES = [
    ("funding $10M-$20M", False), ("funding $10M to $20M", False),
    ("raised $10M-$20M", False), ('funding 10–20 מיליון ש"ח', False),
    ("שכר 30–40 אלף", True), ("שכר 30–40 אלף; גייסנו $20M", True),
    ("salary up to 180000 after funding $20M", False),
    ("salary up to 180000; funding $20M", True),
    ("salary was raised to $150k", True), ("salary has been raised to $150k", True),
    ("base pay was raised to €90k", True), ("salary raised to $150k", True),
    ("salary $160k with funding $12M", False),
    ("raised $12M with salary $160k", True),
    ("גייסנו $20M ושכר ₪35,000 בחודש", True),
    ("שכר תחרותי, raised up to $20M", False),
    ("funding up to $20M; competitive pay", False),
    ("$150k–$180k base + equity (we raised $40M)", True),
    ("salary ($160k), funding ($20M)", True),
    ("competitive salary (raised $20M)", False),
    ("Salary range $150k–$180k following funding of $20M", False),
    ("funding $10M–$20M, competitive salary", False),
    ("we raised $10M; salary $150k", True),
    ("OTE $200k, Series B $40M", True),
    ("שכר ₪40,000 and raised $10M", True),
    ("raised $10M, שכר 25,000 ₪", True),
    ("up to $200k base, raised $40M", True),
    ("(raised $40M) salary $150k", True),
    ("pay $90k–$110k despite Series B of $40M", False),
    ("funding $40M and up to 180000", True),
    ("OTE $200k–$250k; investors raised $40M", True),
    ("competitive salary up to $180k after we raised $50M", False),
    ("base $150k (raised $40M last year)", False),
    ("raised $10M–$20M", False), ("Series A $10M-$15M", False),
    ("salary seed $150k", False), ("salary Series B $150k", False),
    ("seed salary $150k", False),
    ("customer base raised $500k", False),
    ("competitive salary, raised $10M", False),
    ("competitive salary, raised $500k", False),
    ("competitive salary, raised €10M", False),
    ("competitive pay and raised £5 million", False),
    ("hourly rate raised to $50/hour", True),
    ("rate raised to €50 per hour", True),
    ("hourly rate raised to $45/hr", True), ("wage raised to $50", True),
    ("$1M ARR", False),
    # Joined endpoints must share both pay context and units, with no competing owner.
    ("salary 120k–150k", True), ("salary $120k–funding $150k", False),
    ("salary 30–40 אלף employees", False), ("pay up to 500 employees", False),
    ("salary $150k customers", False), ("salary raised to $150k funding", False),
    ("salary raised from $120k to $150k", False),
    ("hourly rate has been raised to $50/hour", True),
    ('funding ($10M–$20M), competitive salary', False),
    ("salary $150k–20%", False), ("salary $150k–20 percent", False),
]


# The salary fact itself supplies pay context for unopposed currency amounts.
# Mixed non-pay strings still need an independently governed pay candidate.
ROUND6_SALARY_CASES = [
    ("120k-150k EUR", True), ("$200k", True), ('30K-40K ש"ח', True),
    ("₪ 25,000", True), ("$105,000 - $110,000", True),
    ("$200,000 — $235,000 USD", True), ("$110-160k DOE", True),
    ("between $123,000 USD and $172,000 USD", True),
    ("California: $165,000–$225,000. All other states: $146,000–$206,000.", True),
    ("raised $10M; $150k", False), ("$150k; funding $10M", False),
    ("raised $10M and $150k", False), ("$150k and raised $10M", False),
    ("raised $10M and pay $150k base", True),
    ("competitive salary; funding $10M and $150k", False),
    ("headcount $150k", False), ("$150k graduates", False),
    ("$150k years of experience", False), ("$120k–$150k employees", False),
    ("funding $120k–$150k", False), ("$120k–funding $150k", False),
    ("US employees (any location): $150,000–$180,000 USD", True),
]


# Explicit source-span expectations replace the old whole-string contract.
CLEAN_SALARY_SPANS = {
    "salary 120k + 401(k) match up to 6%": "salary 120k",
    "we raised $10M and pay $150k base": "pay $150k base",
    "OTE $200k, Series B $40M": "OTE $200k",
    "salary $150k, funding $10M": "salary $150k",
    "funding $10M, salary $150k": "salary $150k",
    "שכר 30–40 אלף; גייסנו $20M": "שכר 30–40 אלף",
    "salary up to 180000; funding $20M": "salary up to 180000",
    "raised $12M with salary $160k": "salary $160k",
    "גייסנו $20M ושכר ₪35,000 בחודש": "ושכר ₪35,000 בחודש",
    "$150k–$180k base + equity (we raised $40M)": "$150k–$180k base",
    "salary ($160k), funding ($20M)": "$160k",
    "we raised $10M; salary $150k": "salary $150k",
    "שכר ₪40,000 and raised $10M": "שכר ₪40,000",
    "raised $10M, שכר 25,000 ₪": "שכר 25,000 ₪",
    "up to $200k base, raised $40M": "up to $200k base",
    "(raised $40M) salary $150k": "salary $150k",
    "funding $40M and up to 180000": "up to 180000",
    "OTE $200k–$250k; investors raised $40M": "OTE $200k–$250k",
    "$110-160k DOE": "$110-160k",
    "between $123,000 USD and $172,000 USD": "$123,000 USD and $172,000 USD",
    "California: $165,000–$225,000. All other states: $146,000–$206,000.": "$165,000–$225,000",
    "raised $10M and pay $150k base": "pay $150k base",
    "US employees (any location): $150,000–$180,000 USD": "$150,000–$180,000 USD",
    "salary $150k plus 401k matching": "salary $150k",
    "Salary $120k. Raised $10M": "Salary $120k",
}


def expected_salary_facts(candidate, salary, numeric):
    expected = deepcopy(candidate)
    span = CLEAN_SALARY_SPANS.get(salary, salary) if numeric else None
    expected["salary"] = {"value": span, "evidence_quote": salary if span else None}
    if span != salary:
        expected["salary_remark"] = salary
    return expected


@pytest.mark.parametrize(
    "salary, numeric",
    PRECISION_PREVIOUS_SALARY_CASES + ROUND5_SALARY_CASES + ROUND6_SALARY_CASES,
)
def test_round2_salary_extraction_and_payload(salary, numeric):
    candidate = facts()
    candidate["salary"] = {"value": salary, "evidence_quote": salary}
    raw_jd = RAW_JD + "\n" + salary
    result = core.extract_posting(posting(raw_jd), {}, runner=runner_for(candidate))
    expected = expected_salary_facts(candidate, salary, numeric)
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
    + list(CONSERVATIVE_SALARY_REMARKS)
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
        ("Engineer Level One 90000 to 120000 requires a Bachelor of Science degree\n\n"
        "Engineer Level Two 110000 to 140000 requires BS plus 2 years or MS plus 0 years\n\n"
        "Staff Engineer 130000 to 160000 requires BS plus 5 years MS plus 3 years or PhD"),
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
        "$50/hour",
        "50 per hour",
        "שכר 35000 בחודש", '35,000 ש״ח לחודש', "35,000 שקלים בחודש",
        "שכר 25,000-30,000 ₪", "עד 35 אלף",
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
    expected = expected_salary_facts(candidate, salary, True)
    assert result["facts"] == expected
    assert build_payload(result, raw_jd).facts == expected


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


# Round 7 explicitly asserts the persisted pay span, not just numeric presence.
ROUND7_SALARY_SPANS = [
    ("$90-$150+/hr", "$90-$150+/hr"),
    ("between $123,000 USD and $172,000 USD", "$123,000 USD and $172,000 USD"),
    ("US$185,000–$300,000", "US$185,000–$300,000"),
    ("salary $130k–$160k; raised €25M", "salary $130k–$160k"),
    ("שכר ₪30,000 בחודש; גייסנו $20M", "שכר ₪30,000 בחודש"),
    ("competitive salary; funding $10M–$20M", None),
    ("competitive pay; 500 employees", None),
    ("Competitive salary; our customer base now totals 150k", None),
    ("Competitive salary; our customer base has now reached 150k", None),
    ("Competitive salary; revenue grew to a total of $10M annually", None),
    ("Competitive salary; we raised a total of approximately $10M at our base", None),
    ("Competitive salary; funding secured by our growing company: $10M base investment", None),
    ("Competitive salary; funding $10M and $20M base capital", None),
    ("$150k–$180k base + equity (we raised $40M)", "$150k–$180k base"),
    ("US employees (any location): $200,700 — $250,900 USD", "$200,700 — $250,900 USD"),
    ("US employees (any location): $150,000–$180,000 USD", "$150,000–$180,000 USD"),
    ("500 employees", None), ("500 locations", None),
    ("500 עובדים", None), ("500 employees: $150k", None),
    ("$150k base", "$150k base"), ("base salary $150k", "base salary $150k"),
    ("salary: $150k", "salary: $150k"), ("$40/hr", "$40/hr"),
    ("₪30,000 בחודש", "₪30,000 בחודש"),
    ("Competitive salary; our customer base serves more than a million users at $150k", None),
    ("Competitive salary; $150k base customers", None),
    ("Competitive salary; $150k base investment", None),
    ("Competitive salary; $150k base capital", None),
    ("Competitive salary; base capital $150k", None),
    ("Competitive salary; investment of $150k", None),
    ("Competitive salary; revenue $10M and $20M annually", None),
    ("Competitive salary; funding $10M and $20M at our base", None),
]


P9C_SALARY_SPANS = [
    ("Competitive salary; $5M base (capital investment)", None),
    ("Competitive salary; $5M base (annual recurring revenue)", None),
    ("Competitive salary; $5M base (ARR)", None),
    ("Competitive salary; ARR $10M, up to $20M annually", None),
    ("Competitive salary; revenue $8M, up to $10M annually", None),
    ("Competitive salary; revenue $8M, $10M annually, up to $12M yearly", None),
    ("Competitive salary; ARR $10M, $20M base", None),
    ("שכר תחרותי; הכנסות שנתיות של ₪20 מיליון", None),
    ("שכר תחרותי; מחזור שנתי של ₪20 מיליון", None),
    ("שכר תחרותי; הכנסות ₪10 מיליון, עד ₪20 מיליון בשנה", None),
    ("שכר תחרותי; ARR של ₪20 מיליון", None),
    ("שכר תחרותי; ARR של ₪10 מיליון, עד ₪20 מיליון בשנה", None),
    ("Competitive salary; installed base of 120k", None),
    ("Competitive salary; subscriber base of 250k", None),
    ("Competitive salary; client base of 40k", None),
    ("Competitive salary; knowledge base of 10k articles", None),
    ("Competitive salary; our base is $5M", None),
    ("base of $120k", None),
    ("base is $120k", None),
    ("Competitive salary; $5M base subscribers", None),
    ("Competitive salary; $5M base (subscribers)", None),
    ("ARR $10M, salary $150k", "salary $150k"),
    ("ARR $10M, up to $200k base salary", "up to $200k base salary"),
    ("revenue $8M, base pay is $150k", "base pay is $150k"),
    ("הכנסות ₪20 מיליון, שכר ₪32,000 בחודש", "שכר ₪32,000 בחודש"),
    ("מחזור ₪20 מיליון; שכר ₪32,000 בחודש", "שכר ₪32,000 בחודש"),
    ("שכר בסיס של ₪32,000 בחודש", "₪32,000 בחודש"),
    ("base salary of $120k", "base salary of $120k"),
    ("base pay is $120k", "base pay is $120k"),
    ("base comp $120k", "base comp $120k"),
    ("$120k base", "$120k base"),
    ("$120k base salary", "$120k base salary"),
    ("$150k–$180k base + equity (we raised $40M)", "$150k–$180k base"),
    ("Salary €90k–£110k base; funding $8M", "Salary €90k–£110k base"),
    ("Salary USD 120,000–CAD 160,000 per year", "Salary USD 120,000–CAD 160,000 per year"),
]


@pytest.mark.parametrize("salary, span", ROUND7_SALARY_SPANS + [
    pytest.param(salary, span, id=f"p9c-{index}")
    for index, (salary, span) in enumerate(P9C_SALARY_SPANS)
])
def test_round7_clean_salary_span(salary, span):
    candidate = facts()
    candidate["salary"] = {"value": salary, "evidence_quote": salary}
    raw_jd = RAW_JD + "\n" + salary
    result = core.extract_posting(posting(raw_jd), {}, runner=runner_for(candidate))
    payload = build_payload(result, raw_jd)
    assert payload.facts == result["facts"]
    assert payload.facts["salary"]["value"] == span
    assert payload.facts["salary"]["evidence_quote"] == (salary if span else None)
    assert payload.facts.get("salary_remark") == (salary if span != salary else None)
    assert candidate["salary"]["value"] == salary
