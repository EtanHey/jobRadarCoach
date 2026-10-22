"""Public geographic excerpts from the 21-row P8 recon; synthetic local profile."""

import json
import re
from collections import Counter
from pathlib import Path

import pytest

from scraper.eligibility import decide_location_eligibility

PROFILE = {
    "candidate": {
        "location": "Central Israel",
        "open_to": {
            "geographies": ["Central Israel", "Remote"],
            "relocation": False,
        },
    }
}
EVIDENCE = json.loads(
    (Path(__file__).parent / "fixtures/eligibility-triage.json").read_text()
)
ADVERSARIAL = json.loads(
    (Path(__file__).parent / "fixtures/eligibility-adversarial.json").read_text()
)


@pytest.mark.parametrize("case_id,location,jd,expected", ADVERSARIAL)
def test_reviewer_adversarial(case_id, location, jd, expected):
    result = decide_location_eligibility(
        {"location": location, "raw_jd": jd}, None, PROFILE
    )
    assert result["eligibility"] == expected, case_id


@pytest.mark.parametrize("city", ["Haifa", "Yokneam", "Jerusalem"])
def test_jd_office_scope_respects_israel_wide_profile(city):
    profile = {"candidate.open_to.geographies": ["Israel"]}
    assert decide_location_eligibility(
        {"location": "Israel", "raw_jd": f"On-site in {city}"}, None, profile
    )["eligibility"] == "eligible"


@pytest.mark.parametrize("location,jd,expected", [
    ("Remote", "Candidates must reside in Israel", "eligible"),
    ("Israel", "Not remote worldwide, excluding Israel", "blocked"),
])
def test_permission_and_exclusion_survive_neighboring_scope(location, jd, expected):
    assert decide_location_eligibility(
        {"location": location, "raw_jd": jd}, None, PROFILE
    )["eligibility"] == expected


@pytest.mark.parametrize("evidence_id,location,quote,expected", EVIDENCE)
def test_triage_evidence(evidence_id, location, quote, expected):
    result = decide_location_eligibility(
        {"id": evidence_id, "location": location, "raw_jd": quote}, None, PROFILE
    )
    assert result["eligibility"] == expected
    assert '"' in result["eligibility_reason"]
    assert any(
        excerpt in quote or excerpt in location
        for excerpt in re.findall(r'"([^"]+)"', result["eligibility_reason"])
    )


def test_evidence_totals():
    assert Counter(
        decide_location_eligibility({"location": loc, "raw_jd": jd}, None, PROFILE)[
            "eligibility"
        ]
        for _, loc, jd, _ in EVIDENCE
    ) == {"blocked": 19, "unknown": 2}


@pytest.mark.parametrize(
    "location,jd,expected",
    [
        ("Tel Aviv-Yafo", "Work from our office", "eligible"),
        ("הרצליה", "Hybrid", "eligible"),
        ("Israel", "Hybrid", "eligible"),
        ("Remote", "Remote worldwide", "eligible"),
        ("Remote", "Remote from Israel", "eligible"),
        ("Remote", "Remote within Europe only", "blocked"),
        ("Berlin, Germany", "On-site Berlin", "blocked"),
        ("Tel Aviv", "Must reside in the US", "unknown"),
        ("Remote", "Remote worldwide. Must reside in the US", "unknown"),
        ("Remote", "Flexible hours", "unknown"),
        (None, "Engineering role", "unknown"),
        ("Tel Aviv, United States", "", "unknown"),
        ("United States", "We serve customers in Israel and worldwide", "unknown"),
        ("United States", "US citizenship required", "unknown"),
    ],
)
def test_location_rules(location, jd, expected):
    assert (
        decide_location_eligibility(
            {"location": location, "raw_jd": jd}, None, PROFILE
        )["eligibility"]
        == expected
    )


def test_us_citizenship_does_not_override_residency():
    profile = {**PROFILE, "citizenship": ["US", "Israel"]}
    assert (
        decide_location_eligibility(
            {"location": "Remote", "raw_jd": "Must reside in the US"}, None, profile
        )["eligibility"]
        == "blocked"
    )


def test_extracted_quote_is_used_but_unverified_quote_cannot_grant_a_pass():
    posting = {"location": "Remote", "raw_jd": "Remote U.S. only"}
    extraction = {
        "facts": {"remote": {"value": True, "evidence_quote": "Remote U.S. only"}}
    }
    assert (
        decide_location_eligibility(posting, extraction, PROFILE)["eligibility"]
        == "blocked"
    )
    extraction["facts"]["remote"]["evidence_quote"] = "Remote worldwide"
    assert (
        decide_location_eligibility(posting, extraction, PROFILE)["eligibility"]
        == "blocked"
    )


def test_israel_wide_profile_accepts_noncentral_israeli_office():
    profile = {
        "candidate.open_to.geographies": ["Israel"],
        "candidate.location": "Israel",
    }
    assert (
        decide_location_eligibility(
            {"location": "Kibbutz Sasa, Israel", "raw_jd": "On-site"}, None, profile
        )["eligibility"]
        == "eligible"
    )


@pytest.mark.parametrize(
    "location,jd,expected",
    [
        ("Remote", "Our remote team serves US customers", "unknown"),
        ("Remote", "Remote in Germany only", "blocked"),
        ("Remote", "Remote within Canada, the US and Israel", "eligible"),
        ("Remote", "Not required to reside in the US", "unknown"),
        (None, "On-site Berlin, Germany", "blocked"),
        ("Remote", "Not remote worldwide", "unknown"),
    ],
)
def test_scope_requires_role_specific_affirmative_evidence(location, jd, expected):
    assert (
        decide_location_eligibility(
            {"location": location, "raw_jd": jd}, None, PROFILE
        )["eligibility"]
        == expected
    )


def test_verified_extracted_location_is_a_fallback_for_missing_location():
    result = decide_location_eligibility(
        {"raw_jd": "Office: Herzliya"},
        {
            "facts": {
                "location": {"value": "Herzliya", "evidence_quote": "Office: Herzliya"}
            },
        },
        PROFILE,
    )
    assert result["eligibility"] == "eligible"
    assert '"Herzliya"' in result["eligibility_reason"]


@pytest.mark.parametrize(
    "location,jd,expected",
    [
        ("Remote", "Candidates must reside in the US or Israel", "eligible"),
        ("United States", "Build hybrid cloud infrastructure", "unknown"),
        ("Kibbutz Sasa, Israel", "Build hybrid mobile apps", "unknown"),
    ],
)
def test_inclusive_residency_and_technical_hybrid_are_not_blockers(
    location, jd, expected
):
    assert (
        decide_location_eligibility(
            {"location": location, "raw_jd": jd}, None, PROFILE
        )["eligibility"]
        == expected
    )
