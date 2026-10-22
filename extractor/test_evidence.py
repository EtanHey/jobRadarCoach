from __future__ import annotations

import pytest

from extractor.evidence import ExtractionValidationError, derive_remote_fact, validate_facts
from scraper.brain_contract import BrainValidationError


RAW_JD = """Senior Backend Engineer
Location: Tel Aviv, Israel. Remote within Israel.
Build TypeScript and Node.js API services.
Salary: $120,000-$150,000 annually.
"""


def facts() -> dict[str, object]:
    return {
        "location": {"value": "Tel Aviv, Israel", "evidence_quote": "Tel Aviv, Israel"},
        "remote": {"value": True, "evidence_quote": "Remote within Israel"},
        "seniority": {"value": "Senior", "evidence_quote": "Senior Backend Engineer"},
        "stack": [
            {"value": "TypeScript", "evidence_quote": "TypeScript"},
            {"value": "Node.js", "evidence_quote": "Node.js"},
        ],
        "salary": {
            "value": "$120,000-$150,000 annually",
            "evidence_quote": "$120,000-$150,000 annually",
        },
    }


def remote_only_facts(value: bool, quote: str) -> dict[str, object]:
    return {
        "location": {"value": None, "evidence_quote": None},
        "remote": {"value": value, "evidence_quote": quote},
        "seniority": {"value": None, "evidence_quote": None},
        "stack": [],
        "salary": {"value": None, "evidence_quote": None},
    }


@pytest.mark.parametrize(("raw_jd", "quote", "expected"), [
    ("Remote work is available.", "Remote work is available", True),
    ("This is an office-based role.", "office-based", False),
    ("This is not a remote role.", "remote role", None),
    ("Flexible hours are available.", "Flexible hours", None),
])
def test_remote_fact_is_derived_only_from_self_supporting_source_evidence(
    raw_jd: str, quote: str, expected: bool | None
) -> None:
    derived = derive_remote_fact(quote, raw_jd)
    assert derived == {
        "value": expected,
        "evidence_quote": quote if expected is not None else None,
    }
    validate_facts(
        {
            **remote_only_facts(True, "Remote work"),
            "remote": derived,
        },
        raw_jd,
    )


def test_unknown_remote_requires_no_evidence_quote() -> None:
    assert derive_remote_fact(None, "No work mode is stated.") == {
        "value": None,
        "evidence_quote": None,
    }


@pytest.mark.parametrize("condition", [
    "Hybrid",
    "This role is hybrid.",
    "This is a hybrid role.",
    "Location: Tel Aviv (Hybrid).",
    "מיקום: תל אביב (היברידי).",
    "With hybrid work, we combine office time and remote work.",
    "Work model: hybrid.",
    "היברידי",
    "עבודה היברידית.",
    "2 days a week in office.",
    "We require three days a week in the office and two days at home.",
    "You must be in the office 2 days per week.",
    "You may work remotely but must be in the office 2 days per week.",
    "3 ימים בשבוע במשרד.",
    "נדרשים 2 ימים בשבוע במשרד.",
    "יומיים בשבוע במשרד ושלושה ימים מהבית.",
])
def test_attendance_outside_remote_quote_prevents_fully_remote(condition):
    raw_jd = f"Remote work is available.\n\n{condition}"
    assert derive_remote_fact("Remote work is available", raw_jd) == {
        "value": None, "evidence_quote": None,
    }
    with pytest.raises(BrainValidationError, match="remote value conflicts"):
        validate_facts(remote_only_facts(True, "Remote work is available"), raw_jd)


@pytest.mark.parametrize("condition", [
    "We build hybrid cloud systems.",
    "Experience with hybrid retrieval is required.",
    "Experience building a hybrid model is required.",
    "There is no hybrid work policy.",
    "This role is not hybrid.",
    "No office attendance is required.",
    "You may optionally visit the office.",
    "0 days a week in the office.",
    "Our office is open 2 days a week.",
])
def test_non_attendance_mentions_preserve_explicit_remote(condition):
    raw_jd = f"Remote work is available.\n\n{condition}"
    assert derive_remote_fact("Remote work is available", raw_jd) == {
        "value": True, "evidence_quote": "Remote work is available",
    }


@pytest.mark.parametrize("condition", [
    "Some roles in our sales team are being hired for in-person hybrid work.",
    "Other platform roles require 3 days a week in the office.",
    "Hybrid work is required for other engineering teams.",
    "Certain teams work in the office 5 days per week.",
])
def test_other_role_attendance_preserves_this_roles_remote_evidence(condition):
    raw_jd = f"Remote work is available. {condition}"
    assert derive_remote_fact("Remote work is available", raw_jd) == {
        "value": True, "evidence_quote": "Remote work is available",
    }


@pytest.mark.parametrize(("condition", "mode"), [
    ("This role requires 5 days a week from our office.", "on-site"),
    ("This role requires five office days per week.", "on-site"),
    ("You must be in the office five days per week.", "on-site"),
    ("This role is full-time in office.", "on-site"),
    ("Our work model is fully in person.", "on-site"),
    ("This role requires 5/5 days in the office.", "on-site"),
    ("נדרשים 5 ימים בשבוע במשרד.", "on-site"),
    ("This role requires four days a week in the office.", "hybrid"),
    ("All staff work in the office 3 days per week.", "hybrid"),
    ("Other roles work remotely; this role requires five office days per week.", "on-site"),
    ("Other teams work remotely, but this role requires 3 days a week in office.", "hybrid"),
    ("You may work in office five days per week.", None),
    ("No full-time in office attendance is required.", None),
    ("10 days in the office for onboarding.", None),
    ("5 days in the office for onboarding.", None),
    ("25 days in office annually.", None),
])
def test_attendance_classifies_full_and_partial_office_schedules(condition, mode):
    from extractor.evidence import attendance_evidence

    evidence = attendance_evidence(condition)
    assert (evidence[0] if evidence else None) == mode
    if evidence:
        assert evidence[1] in condition


def test_full_time_office_condition_blocks_remote_quote():
    raw_jd = "Remote work is available. This role requires five office days per week."
    assert derive_remote_fact("Remote work is available", raw_jd) == {
        "value": None, "evidence_quote": None,
    }


@pytest.mark.parametrize("quote", [
    "We are a remote-first company.",
    "Our engineering team works remotely.",
    "Benefits include remote work support.",
])
def test_non_role_remote_wording_does_not_establish_role_availability(
    quote: str,
) -> None:
    assert derive_remote_fact(quote, quote) == {
        "value": None,
        "evidence_quote": None,
    }
    with pytest.raises(BrainValidationError, match="remote value conflicts"):
        validate_facts(remote_only_facts(True, quote), quote)


@pytest.mark.parametrize("mutation", [
    lambda value: value["location"].update(
        value="Jerusalem", evidence_quote="Tel Aviv, Israel"
    ),
    lambda value: value["seniority"].update(value=None),
    lambda value: value["remote"].update(value=False),
    lambda value: value["stack"][0].update(value="Script"),
    lambda value: value["stack"].append(
        {"value": "typescript", "evidence_quote": "TypeScript"}
    ),
])
def test_semantically_unsupported_or_ambiguous_facts_fail_closed(mutation) -> None:
    invalid = facts()
    mutation(invalid)
    with pytest.raises(BrainValidationError):
        validate_facts(invalid, RAW_JD)


@pytest.mark.parametrize("quote", [
    "This is not a remote position.",
    "Remote work is not available.",
    "We do not offer remote work.",
    "The role is no longer remote.",
    "Remote work is unavailable.",
    "Remote work is prohibited.",
    "Candidates cannot work remotely.",
    "This is a non-remote role.",
    "Remote work isn't available.",
    "Remote work is not currently available.",
    "Remote work will not be available.",
    "Remote work won't be available.",
    "Remote work would not be permitted.",
    "Remote work is not an option.",
    "Remote work cannot be offered.",
])
def test_remote_polarity_rejects_separated_and_omitted_negation(quote: str) -> None:
    with pytest.raises(BrainValidationError, match="remote value conflicts"):
        validate_facts(remote_only_facts(True, quote), quote)

    validate_facts(remote_only_facts(False, quote), quote)


@pytest.mark.parametrize(("raw_jd", "quote"), [
    ("This is not a remote position.", "a remote position"),
    ("Remote work is not available.", "Remote work"),
    ("We do not offer remote work.", "remote work"),
    ("The role is no longer remote.", "remote"),
    ("Remote work is unavailable.", "Remote work"),
])
def test_remote_polarity_rejects_quotes_that_omit_source_negation(
    raw_jd: str,
    quote: str,
) -> None:
    for value in (True, False):
        with pytest.raises(BrainValidationError, match="remote value conflicts"):
            validate_facts(remote_only_facts(value, quote), raw_jd)


@pytest.mark.parametrize("quote", [
    "This is a remote position.",
    "We do not offer office parking, but remote work is available.",
    "We cannot provide parking and remote work is available.",
    "We do not offer parking while remote work is available.",
    "Remote work is available.",
    "Remote work is available, but office parking is not available.",
    "Remote work is available and office parking is unavailable.",
    "Remote work is available; office parking is not available.",
    "Remote work is available, not required.",
    "Remote work is not only available, but encouraged.",
    "Not only is remote work available, it is encouraged.",
    "Candidates may work remotely.",
    "This role is not onsite, and remote work is available.",
    "The role is not office-based and may be performed remotely.",
])
def test_remote_polarity_preserves_explicit_positive_evidence(quote: str) -> None:
    validate_facts(remote_only_facts(True, quote), quote)

    with pytest.raises(BrainValidationError, match="remote value conflicts"):
        validate_facts(remote_only_facts(False, quote), quote)


def test_explicit_workable_onsite_token_preserves_remote_polarity() -> None:
    quote = "Workplace:** on_site"
    validate_facts(remote_only_facts(False, quote), quote)
    with pytest.raises(BrainValidationError, match="remote value conflicts"):
        validate_facts(remote_only_facts(True, quote), quote)


@pytest.mark.parametrize(("raw_jd", "quote", "value"), [
    ("Our headquarters are in Tel Aviv.", "Tel Aviv", "Tel Aviv"),
    ("We are headquartered in London.", "London", "London"),
    ("Our offices are located in Berlin and Paris.", "Berlin and Paris", "Berlin and Paris"),
    ("Our regional headquarters are in New York, Tel Aviv, and London.", "Tel Aviv", "Tel Aviv"),
    ("Pagaya has offices in New York and Tel Aviv.", "New York and Tel Aviv", "New York and Tel Aviv"),
    ("Work with customers within the Israeli market.", "within the Israeli market", "Israeli market"),
    ("Panax is a startup based in Tel Aviv and New York.", "Tel Aviv and New York", "Tel Aviv and New York"),
])
def test_company_locations_and_customer_markets_do_not_establish_job_location(
    raw_jd: str, quote: str, value: str
) -> None:
    candidate = remote_only_facts(None, None)
    candidate["location"] = {"value": value, "evidence_quote": quote}
    with pytest.raises(BrainValidationError, match="job location"):
        validate_facts(candidate, raw_jd)


def test_explicit_role_location_survives_company_office_context() -> None:
    raw_jd = "Our regional headquarters are in New York and Tel Aviv. This role is based in Tel Aviv."
    candidate = remote_only_facts(None, None)
    candidate["location"] = {"value": "Tel Aviv", "evidence_quote": "This role is based in Tel Aviv"}
    validate_facts(candidate, raw_jd)


def test_role_prefix_cannot_bypass_company_geography_check() -> None:
    quote = "This role is based at our regional headquarters in Tel Aviv"
    candidate = remote_only_facts(None, None)
    candidate["location"] = {"value": "Tel Aviv", "evidence_quote": quote}
    with pytest.raises(ExtractionValidationError) as rejected:
        validate_facts(candidate, quote)
    assert rejected.value.category == "location_context"


def test_salary_quote_failure_preserves_other_evidence():
    candidate = facts()
    expected = facts()
    candidate["salary"]["evidence_quote"] = "$120,000 to $150,000"
    validate_facts(candidate, RAW_JD)
    expected["salary"] = {"value": None, "evidence_quote": None}
    expected["salary_remark"] = "$120,000-$150,000 annually"
    assert candidate == expected


@pytest.mark.parametrize("condition", [
    "Interviews are fully in-person.",
    "Onboarding week is fully in-person.",
    "Process includes a fully in-person interview day.",
    "Fully in-person onboarding for the first week.",
    "Our events are fully in person.",
    "This role includes fully in-person interviews.",
    "The interview for this role is fully in-person.",
    "Other teams have fully in-person roles.",
    "We require three days in the office for onboarding.",
    "We require five office days per quarter.",
    "We require five office days for onboarding.",
    "This role requires five office days.",
    "Training requires three days a week in the office for the first month.",
    "Initially, this role requires five days a week in the office.",
    "During onboarding, this role is full-time in office.",
    "This role is fully in-person for the first week.",
    "This role requires three days a week in office for two weeks.",
    "נדרשים 3 ימים במשרד.",
])
def test_temporary_or_non_role_attendance_preserves_remote(condition):
    from extractor.evidence import attendance_evidence

    raw_jd = "This role is fully remote. " + condition
    assert attendance_evidence(raw_jd) is None
    assert derive_remote_fact("This role is fully remote", raw_jd)["value"] is True


@pytest.mark.parametrize("condition", [
    "This role is fully in-person.",
    "This is a fully in-person position.",
    "Work arrangement: fully in person.",
    "This role requires three days in the office per week.",
])
def test_ongoing_role_arrangements_are_retained(condition):
    from extractor.evidence import attendance_evidence

    evidence = attendance_evidence(condition)
    assert evidence is not None
    assert evidence[0] == ("hybrid" if "three days" in condition else "on-site")


@pytest.mark.parametrize("condition", [
    "Location: Anywhere (Onsite / Hybrid / Remote - Based on Client Requirement).",
    "This position offers remote or hybrid work arrangements, with a preference for local candidates.",
    "Work model: hybrid or remote.",
    "This role is hybrid depending on client requirements.",
    "A hybrid work arrangement is preferred.",
])
def test_unresolved_work_arrangements_abstain(condition):
    from extractor.evidence import attendance_evidence

    evidence = attendance_evidence(condition)
    assert evidence == ("unknown", condition.rstrip("."))
    assert derive_remote_fact("remote", condition)["value"] is None
