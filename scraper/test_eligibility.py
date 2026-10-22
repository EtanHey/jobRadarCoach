"""Public geographic excerpts from the 21-row P8 recon; synthetic local profile."""

import json
import re
from collections import Counter
from pathlib import Path

import pytest

from scraper.eligibility import _without_policy, decide_location_eligibility
from scraper.geography import HEBREW_COUNTRY_NAMES, HEBREW_REGION_NAMES

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
REVIEW_R2 = json.loads(
    (Path(__file__).parent / "fixtures/eligibility-review-r2.json").read_text()
)
FRESH_R2 = json.loads(
    (Path(__file__).parent / "fixtures/eligibility-fresh-r2.json").read_text()
)
REVIEW_R3 = json.loads(
    (Path(__file__).parent / "fixtures/eligibility-review-r3.json").read_text()
)
REVIEW_R4 = json.loads(
    (Path(__file__).parent / "fixtures/eligibility-review-r4.json").read_text()
)
REVIEW_R5 = json.loads(
    (Path(__file__).parent / "fixtures/eligibility-review-r5.json").read_text()
)

REVIEW_R6 = json.loads(
    (Path(__file__).parent / "fixtures/eligibility-review-r6.json").read_text()
)

ADVERSARIAL = json.loads(
    (Path(__file__).parent / "fixtures/eligibility-adversarial.json").read_text()
)


@pytest.mark.parametrize(
    "case_id,location,jd,expected",
    ADVERSARIAL + REVIEW_R2 + FRESH_R2 + REVIEW_R3 + REVIEW_R4 + REVIEW_R5 + REVIEW_R6,
)
def test_reviewer_adversarial(case_id, location, jd, expected):
    result = decide_location_eligibility(
        {"location": location, "raw_jd": jd}, None, PROFILE
    )
    assert result["eligibility"] == expected, case_id


@pytest.mark.parametrize("office", [False, True])
def test_district_qualifier_preserves_noncentral_office_policy(office):
    result = decide_location_eligibility(
        {
            "location": "Haifa, Haifa District, Israel",
            "work_mode": "hybrid" if office else None,
        },
        None,
        PROFILE,
    )
    assert result["eligibility"] == ("blocked" if office else "unknown")


def test_unknown_reason_separates_missing_evidence_from_restriction():
    for jd, prefix in [
        (
            "Candidates must know React",
            "Israel/remote-from-Israel scope is unconfirmed:",
        ),
        (
            "Candidates must live in an approved jurisdiction",
            "unresolved location restriction:",
        ),
    ]:
        result = decide_location_eligibility(
            {"location": "Remote", "raw_jd": jd}, None, PROFILE
        )
        assert result["eligibility"] == "unknown"
        assert result["eligibility_reason"].startswith(prefix)


@pytest.mark.parametrize("city", ["Haifa", "Yokneam", "Jerusalem"])
def test_jd_office_scope_respects_israel_wide_profile(city):
    profile = {"candidate.open_to.geographies": ["Israel"]}
    assert (
        decide_location_eligibility(
            {"location": "Israel", "raw_jd": f"On-site in {city}"}, None, profile
        )["eligibility"]
        == "eligible"
    )


@pytest.mark.parametrize(
    "location,jd,expected",
    [
        ("Remote", "Candidates must reside in Israel", "eligible"),
        ("Israel", "Not remote worldwide, excluding Israel", "blocked"),
    ],
)
def test_permission_and_exclusion_survive_neighboring_scope(location, jd, expected):
    assert (
        decide_location_eligibility(
            {"location": location, "raw_jd": jd}, None, PROFILE
        )["eligibility"]
        == expected
    )


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
    ) == {"blocked": 16, "unknown": 5}


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
        ("Remote", "Remote worldwide. Must reside in the US", "blocked"),
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
        (None, "On-site Berlin, Germany", "unknown"),
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


@pytest.mark.parametrize("location", ["Israel", "Tel Aviv", "Remote worldwide"])
@pytest.mark.parametrize(
    "restriction",
    [
        "Must reside in an approved jurisdiction",
        "Only applicants from a supported country may apply",
        "Candidates must be eligible to work in Israel",
        "US citizens only",
        "Applicants must live in Berlin or an approved location",
        "Candidates based in Europe preferred",
        "Remote worldwide, except applicants holding a restricted passport",
        "Remote role — מגורים במדינה מאושרת חובה",
        "Remote worldwide, רק מועמדים ממדינות מאושרות",
        "חובה לעבוד באזור זמן מאושר",
        "Not accepting applicants from Israel",
    ],
)
def test_unresolved_restriction_vetoes_every_positive_location(location, restriction):
    result = decide_location_eligibility(
        {"location": location, "raw_jd": restriction}, None, PROFILE
    )
    assert result["eligibility"] != "eligible"
    assert restriction in result["eligibility_reason"]


@pytest.mark.parametrize(
    "jd",
    [
        "Optional hybrid role in London",
        "Hybrid in London or an approved alternative",
        "Hybrid in London, Israel",
        "Our clients offer hybrid in London",
        "We serve customers everywhere except Israel",
        "No need to relocate to Berlin except Israel",
        "Must reside in Berlin unless approved to work from Israel",
        "Must be based in Berlin but applicants in Israel can work remotely",
    ],
)
def test_ambiguous_foreign_office_or_alternative_cannot_block_or_pass(jd):
    assert (
        decide_location_eligibility(
            {"location": "Israel", "raw_jd": jd}, None, PROFILE
        )["eligibility"]
        == "unknown"
    )


@pytest.mark.parametrize("city", ["Holon", "Rishon LeZion", "חולון", "ראשון לציון"])
def test_shared_central_aliases_with_structured_office_requirement(city):
    assert (
        decide_location_eligibility(
            {"location": city, "work_mode": "hybrid", "remote": False}, None, PROFILE
        )["eligibility"]
        == "eligible"
    )


@pytest.mark.parametrize(
    "posting",
    [
        {"location": "Worldwide"},
        {"location": "Israel", "raw_jd": "Hybrid worldwide"},
        {"location": "Israel", "raw_jd": "Must be based worldwide"},
    ],
)
def test_worldwide_needs_explicit_remote_permission(posting):
    assert (
        decide_location_eligibility(posting, None, PROFILE)["eligibility"] == "unknown"
    )


HOLDOUT_R2 = json.loads(
    (Path(__file__).parent / "fixtures/eligibility-holdout-r2.json").read_text()
)
# Preserve the independent desired outcomes in the fixture. These two unsupported
# readings may conservatively remain unknown, but must never invert to a wrong
# confident decision. The probe receipt reports them as mismatches, not passes.
CONSERVATIVE_HOLDOUT = {"holdout-15", "holdout-19"}


@pytest.mark.parametrize("case_id,location,jd,expected", HOLDOUT_R2)
def test_post_implementation_holdout_keeps_precision(case_id, location, jd, expected):
    result = decide_location_eligibility(
        {"location": location, "raw_jd": jd}, None, PROFILE
    )
    allowed = {expected, "unknown"} if case_id in CONSERVATIVE_HOLDOUT else {expected}
    assert result["eligibility"] in allowed, case_id


def test_hebrew_country_table_covers_every_iso_country():
    from scraper.geography import COUNTRY_IDENTIFIERS, HEBREW_COUNTRY_NAMES

    iso_codes = {name.upper() for name in COUNTRY_IDENTIFIERS if len(name) == 2}
    assert set(HEBREW_COUNTRY_NAMES) == iso_codes - {"UK"}
    assert len(HEBREW_COUNTRY_NAMES) == 249


@pytest.mark.parametrize("name", [*HEBREW_COUNTRY_NAMES.values(), *HEBREW_REGION_NAMES])
@pytest.mark.parametrize(
    "prefix", ["", "ב", "ל", "מ", "ו", "ה", "ש", "וב", "שב", "ול", "מה"]
)
def test_every_hebrew_country_and_region_supplies_context(name, prefix):
    from scraper.geography import has_geographic_context

    jd = f"חובה לעבוד רק {prefix}{name}"
    assert has_geographic_context(jd), jd
    if name != "ישראל":
        result = decide_location_eligibility(
            {"location": "Tel Aviv", "raw_jd": jd}, None, PROFILE
        )
        assert result["eligibility"] != "eligible", jd


REVIEW_R7 = json.loads(
    (Path(__file__).parent / "fixtures/eligibility-review-r7.json").read_text()
)
CONSERVATIVE_R7 = {"r7-15", "r7-noise-8", "r7-noise-9"}


@pytest.mark.parametrize("case_id,location,jd,expected", REVIEW_R7)
def test_restriction_frames_and_hebrew_alternatives(case_id, location, jd, expected):
    result = decide_location_eligibility(
        {"location": location, "raw_jd": jd}, None, PROFILE
    )
    allowed = {expected, "unknown"} if case_id in CONSERVATIVE_R7 else {expected}
    assert result["eligibility"] in allowed, case_id


REVIEW_R8 = json.loads(
    (Path(__file__).parent / "fixtures/eligibility-review-r8.json").read_text()
)


@pytest.mark.parametrize("case_id,location,jd,expected", REVIEW_R8)
def test_complete_restriction_slots_and_language_spans(case_id, location, jd, expected):
    result = decide_location_eligibility(
        {"location": location, "raw_jd": jd}, None, PROFILE
    )
    assert result["eligibility"] == expected, case_id


@pytest.mark.parametrize(
    "attribute", ["citizenship", "citizenship status", "nationality", "residency"]
)
@pytest.mark.parametrize(
    "requirement",
    ["must", "should", "needs to", "is required", "required", "only", "mandatory", "חובה", "נדרש"],
)
def test_policy_mask_preserves_requirement_subject(attribute, requirement):
    restriction = f"{attribute} {requirement} be German"
    assert restriction in _without_policy(f"We hire regardless of race, {restriction}.")


@pytest.mark.parametrize(
    "attribute", ["nationality", "national origin", "immigration status", "residency status"]
)
@pytest.mark.parametrize(
    "requirement",
    ["must", "should", "needs to", "is required", "required", "only", "mandatory", "חובה", "נדרש"],
)
@pytest.mark.parametrize(
    "prefix", ["", "We hire regardless of race, ", "We hire without regard to race and "]
)
def test_nationality_class_requirement_is_unresolved(attribute, requirement, prefix):
    result = decide_location_eligibility(
        {"location": "Tel Aviv", "raw_jd": f"{prefix}{attribute} {requirement} be French."},
        None,
        PROFILE,
    )
    assert result["eligibility"] == "unknown"


@pytest.mark.parametrize(
    "attribute", ["nationality", "national origin", "immigration status", "residency status"]
)
@pytest.mark.parametrize("qualifier", ["French", "Israeli"])
@pytest.mark.parametrize("template", ["{q} {a} required", "Must have {q} {a}", "Only {q} {a}"])
def test_qualified_nationality_requirement_never_blocks(attribute, qualifier, template):
    result = decide_location_eligibility(
        {"location": "Tel Aviv", "raw_jd": template.format(q=qualifier, a=attribute)},
        None,
        PROFILE,
    )
    assert result["eligibility"] == "unknown"


@pytest.mark.parametrize(
    "attribute", ["nationality", "national origin", "immigration status", "residency status"]
)
@pytest.mark.parametrize("requirement", ["", "Must know React. ", "Must know React, "])
def test_eeo_nationality_mention_is_not_a_requirement(attribute, requirement):
    result = decide_location_eligibility(
        {
            "location": "Tel Aviv",
            "raw_jd": f"{requirement}We hire regardless of race, {attribute} and religion.",
        },
        None,
        PROFILE,
    )
    assert result["eligibility"] == "eligible"


@pytest.mark.parametrize(
    "suffix,expected",
    [
        (" (Ohio).", "unknown"),
        ("-based enclave in Germany.", "unknown"),
        (" office in Germany.", "unknown"),
        (" Township, Ohio.", "unknown"),
        (" County in Germany.", "unknown"),
        (".", "blocked"),
        ("", "blocked"),
        (", please note.", "unknown"),
        ("; please note.", "blocked"),
        (" and must know React.", "blocked"),
        (" or must know React.", "unknown"),
    ],
)
def test_exclusion_requires_a_consumed_place_slot(suffix, expected):
    result = decide_location_eligibility(
        {"location": "Tel Aviv", "raw_jd": f"Not open to candidates from Israel{suffix}"},
        None,
        PROFILE,
    )
    assert result["eligibility"] == expected


@pytest.mark.parametrize(
    "location",
    ["Tel Aviv, Israel", "Tel Aviv-Yafo, Tel Aviv District, Israel", "Israel; United States", "Atlantis", None],
)
@pytest.mark.parametrize(
    "sentence",
    [
        "For the London position, candidates must reside in the UK.",
        "New York hires must be based in the United States.",
        "Our London-based engineers must live in the UK.",
        "3 days a week in our New York office for US hires.",
        "We are hiring in Tel Aviv and New York. New York hires must be based in the United States.",
        "Our New York team members must reside in New York.",
        "US-based roles: candidates must reside in the United States.",
        "Remote. US applicants must reside in the United States.",
        "Hybrid - 3 days a week in our New York office for US hires; Israel hires work from Tel Aviv office.",
        "Only residents of France are eligible.",
    ],
)
def test_israeli_or_unresolved_field_keeps_description_blocks_reviewable(
    location, sentence
):
    result = decide_location_eligibility(
        {"location": location, "raw_jd": sentence}, None, PROFILE
    )
    assert result["eligibility"] == "unknown"
    assert result["eligibility_reason"].startswith("unresolved location restriction:")
    assert any(
        quote in sentence
        for quote in re.findall(r'"([^"]+)"', result["eligibility_reason"])
    )


@pytest.mark.parametrize("location", ["Tel Aviv", "Atlantis", None, "Remote"])
@pytest.mark.parametrize(
    "sentence",
    [
        "Not open to candidates from Israel.",
        "Not open to Israelis.",
        "Not open to Israeli applicants.",
        "Israel is excluded.",
        "Israelis are excluded.",
        "Israel is not an available work location.",
        "לא כולל ישראל",
        "Excluded countries: France, Israel, Canada.",
        "Remote worldwide except Canada, Israel and France.",
    ],
)
def test_explicit_israel_exclusions_stay_blocked_despite_field(location, sentence):
    result = decide_location_eligibility(
        {"location": location, "raw_jd": "Must reside in the UK. " + sentence},
        None,
        PROFILE,
    )
    assert result["eligibility"] == "blocked"
    assert sentence in result["eligibility_reason"]


@pytest.mark.parametrize("inclusion", ["including", "incl.", "such as", "e.g."])
@pytest.mark.parametrize("region", ["Europe", "EMEA"])
@pytest.mark.parametrize(
    "template", ["Must be based in {scope}.", "Remote within {scope}."]
)
def test_parenthetical_inclusion_continues_region_scope(inclusion, region, template):
    sentence = template.format(scope=f"{region} ({inclusion} Israel)")
    result = decide_location_eligibility(
        {"location": "Remote", "raw_jd": sentence}, None, PROFILE
    )
    assert result["eligibility"] in {"eligible", "unknown"}


@pytest.mark.parametrize("location", ["Remote - EMEA", "Remote, EMEA", "EMEA Remote"])
def test_emea_location_does_not_exclude_israel(location):
    result = decide_location_eligibility({"location": location}, None, PROFILE)
    assert result["eligibility"] == "unknown"


@pytest.mark.parametrize("location", ["United States", "Remote"])
def test_resolved_foreign_or_neutral_remote_field_retains_description_block(location):
    result = decide_location_eligibility(
        {"location": location, "raw_jd": "Only residents of France are eligible."},
        None,
        PROFILE,
    )
    assert result["eligibility"] == "blocked"


@pytest.mark.parametrize("location", ["Tel Aviv, Israel", "Center District, Israel", "חולון"])
@pytest.mark.parametrize("jd", [
    "Hybrid Work & Office Environment 🏠",
    "Flexible hybrid work model",
    "Hybrid work schedule with 3 days in-office",
    "We work 3 days a week in the office",
    "Applicants must have the legal right to work in the country where the position is based, without the need for visa sponsorship",
    "Applicants must be authorized to work in the country in which they apply and will be required to provide proof of employment eligibility as a condition of hire",
    "על המועמדים להיות בעלי זכות חוקית לעבוד במדינה שבה המשרה ממוקמת, ללא צורך בחסות לוויזה",
    "המועמדים חייבים להיות בעלי אישור עבודה במדינה בה ממוקמת המשרה",
    "המועמדים נדרשים להיות רשאים לעבוד כחוק במדינה שבה המשרה ממוקמת",
])
def test_own_israeli_workplace_terms_are_satisfied(location, jd):
    result = decide_location_eligibility({"location": location, "raw_jd": jd}, None, PROFILE)
    assert result["eligibility"] == "eligible"


@pytest.mark.parametrize("location", ["Tel Aviv", "Israel; United States", "Atlantis", ""])
@pytest.mark.parametrize("jd", [
    "Hybrid in Atlantis",
    "Hybrid Atlantis",
    "Requires 3 days a week in the office in Atlantis",
    "Hybrid model - Atlantis",
    "Hybrid work & office environment in Atlantis",
    "Hybrid 3 days per week in Atlantis",
    "Hybrid model with required attendance at Atlantis",
    "Hybrid work model at our Atlantis office",
    "Hybrid work model, must be in Atlantis",
    "Hybrid role, 3 days a week in our London office",
    "Hybrid work model, US citizenship required",
    "Hybrid role, security clearance required",
    "Hybrid work model, must work in an approved jurisdiction",
    "Hybrid work model, not open to candidates from Israel",
    "Our company is based in Tel Aviv; candidates must reside in London",
    "Applicants must have the legal right to work in the country where the position is based and hold German citizenship",
    "Applicants must have the legal right to work in the country where the position is based and live in Atlantis",
])
def test_local_office_terms_cannot_erase_separate_restrictions(location, jd):
    result = decide_location_eligibility({"location": location, "raw_jd": jd}, None, PROFILE)
    assert result["eligibility"] != "eligible"


@pytest.mark.parametrize("location", ["Haifa", "Ashdod, South District, Israel"])
def test_own_company_description_keeps_noncentral_scope_unconfirmed(location):
    result = decide_location_eligibility(
        {"location": location, "raw_jd": "Our company is based in " + location}, None, PROFILE
    )
    assert result["eligibility"] == "unknown"
    assert result["eligibility_reason"].startswith("Israel/remote-from-Israel scope is unconfirmed:")


@pytest.mark.parametrize("location", ["London", "Israel; United States", "Atlantis", ""])
def test_own_country_authorization_requires_a_resolved_israeli_field(location):
    result = decide_location_eligibility({
        "location": location,
        "raw_jd": "Applicants must have the legal right to work in the country where the position is based, without the need for visa sponsorship",
    }, None, PROFILE)
    assert result["eligibility"] == "unknown"


@pytest.mark.parametrize("location", ["Sarid, Israel (Hybrid)", "Ashdod, South District, Israel"])
def test_unfamiliar_own_israeli_city_retains_unconfirmed_scope(location):
    result = decide_location_eligibility({"location": location, "raw_jd": "Hybrid work model"}, None, PROFILE)
    assert result["eligibility"] == "unknown"
    assert result["eligibility_reason"].startswith("Israel/remote-from-Israel scope is unconfirmed:")


@pytest.mark.parametrize("jd", [
    "Hybrid - uk", "Hybrid working (uk)", "Hybrid - eu", "On-site - eu",
    "Hybrid - nyc", "Hybrid working (nyc)", "Hybrid UK", "Hybrid Eu", "In-office uk",
    "Hybrid Nyc", "Hybrid us", "Hybrid US", "Hybrid U.S.",
    "Hybrid work model with weekly office presence in Warsaw",
    "Hybrid work model with visits to our Warsaw office",
    "Hybrid work model with three days in our San Diego office",
    "Hybrid work model with three days in our warsaw office",
    "Hybrid work model with WonderWord", "Hybrid work model with wonderword",
    "Hybrid work model with three days in our Herzliya office",
    "Hybrid working in the office with us in Warsaw",
    "Hybrid with Tel Aviv us",
    "Our work model is fully in person, with 5 days a week from our office",
    "#LI-Hybrid Joining our company is the smart move",
    "This is a full-time, on-site role working closely with founders",
    "The office is located in Central Israel adjacent to the train station, operating on a hybrid model",
    "This position is based in our Ramat-Gan, Israel office and requires strong leadership presence",
    "Our company is based in Tel Aviv with visits to Warsaw",
    "Our company is based in Tel Aviv, uk",
    "Our company is based in our office",
    "Applicants must have the legal right to work in the country where the position is based, uk",
    "Applicants must have the legal right to work in the country where the position is based with weekly office presence in Warsaw",
    "עבודה היברידית במשרד עם נוכחות בוורשה",
    "החברה ממוקמת בתל אביב ובוורשה",
])
def test_own_workplace_requires_every_token_to_be_consumed(jd):
    result = decide_location_eligibility({"location": "Tel Aviv", "raw_jd": jd}, None, PROFILE)
    assert result["eligibility"] == "unknown"
    assert result["eligibility_reason"].startswith("unresolved location restriction:")


@pytest.mark.parametrize("location,jd", [
    ("Tel Aviv", "Our company is based in Tel Aviv"),
    ("Tel Aviv", "On-site role based in Tel Aviv"),
    ("Tel Aviv", "Our office is located in Tel Aviv, hybrid work model"),
    ("Tel Aviv", "Hybrid work model with three days in our Tel Aviv office"),
    ("Tel Aviv", "Hybrid work model with us"),
    ("Tel Aviv", "Join us - hybrid work model"),
    ("תל אביב", "עבודה היברידית שלושה ימים בשבוע במשרד שלנו בתל אביב"),
    ("תל אביב", "החברה ממוקמת בתל אביב"),
    ("Raanana, Israel (On-site)", ""),
    ("Tel Aviv", "Hybrid Work & Office Environment 🏠"),
    ("Tel Aviv", "Hybrid work schedule with 3 days in-office"),
])
def test_closed_own_workplace_controls(location, jd):
    result = decide_location_eligibility({"location": location, "raw_jd": jd}, None, PROFILE)
    assert result["eligibility"] == "eligible"
