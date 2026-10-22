"""Synthetic regressions for the deferred P8b frames and geo contradictions."""

import pytest

from scraper.eligibility import decide_location_eligibility
from scraper.test_eligibility import PROFILE


@pytest.mark.parametrize(
    "jd",
    [
        "This role is limited to German candidates",
        "This role is limited to Germany",
        "The role is restricted to Canada",
        "Hiring is limited to the United Kingdom",
        "German-based applicants may apply",
        "UK-based applicants are welcome",
        "המשרה מיועדת למועמדים גרמנים",
        "המשרה מיועדת לגרמניה",
        "דרושים מועמדים אמריקאים",
    ],
)
@pytest.mark.parametrize("location", ["Tel Aviv, Israel", "Remote", None])
def test_deferred_applicant_frames_veto_unqualified_eligibility(jd, location):
    result = decide_location_eligibility(
        {"location": location, "raw_jd": jd}, None, PROFILE
    )
    assert result["eligibility"] == "unknown"
    assert result["eligibility_reason"].startswith("unresolved location restriction:")


@pytest.mark.parametrize(
    "jd",
    [
        "This role is limited to Israeli candidates",
        "Israel-based applicants may apply",
        "המשרה מיועדת למועמדים ישראלים",
        "המשרה מיועדת לישראל",
        "דרושים מועמדים ישראלים",
        "German-speaking applicants may apply",
        "דרושים מועמדים דוברי גרמנית",
    ],
)
def test_israeli_applicant_and_language_controls(jd):
    assert decide_location_eligibility(
        {"location": "Tel Aviv, Israel", "raw_jd": jd}, None, PROFILE
    )["eligibility"] == "eligible"


@pytest.mark.parametrize(
    "jd", ["US residents only", "Remote, US residents only", "Remote + US residents only"]
)
@pytest.mark.parametrize(
    "location,expected",
    [
        ("Remote", "blocked"),
        ("Israel", "unknown"),
        (None, "unknown"),
        ("Atlantis", "unknown"),
    ],
)
def test_country_first_residence_keeps_field_precedence(jd, location, expected):
    assert decide_location_eligibility(
        {"location": location, "raw_jd": jd}, None, PROFILE
    )["eligibility"] == expected


@pytest.mark.parametrize(
    "slot,expected",
    [
        ("Israel", "eligible"),
        ("Israel or US", "eligible"),
        ("Atlantis", "unknown"),
        ("US or Atlantis", "unknown"),
        ("US or Israel", "eligible"),
    ],
)
def test_country_first_residence_consumes_every_alternative(slot, expected):
    assert decide_location_eligibility(
        {"location": "Remote", "raw_jd": f"{slot} residents only"}, None, PROFILE
    )["eligibility"] == expected


@pytest.mark.parametrize(
    "location,expected",
    [
        ("San Francisco, CA • New York, NY • United States", "blocked"),
        ("Tel Aviv, Israel • New York, NY • United States", "unknown"),
        ("Atlantis • New York, NY • United States", "unknown"),
        ("Tel Aviv, Israel • Herzliya, Israel", "eligible"),
        ("San Francisco, IL • United States", "blocked"),
    ],
)
def test_bullet_location_alternatives_preserve_every_field(location, expected):
    assert decide_location_eligibility(
        {"location": location, "work_mode": "hybrid"},
        None,
        PROFILE,
    )["eligibility"] == expected


@pytest.mark.parametrize(
    "jd",
    [
        "Eligible countries: Poland, Portugal, Hungary, Romania, or South Africa.",
        "Location eligibility: The original job listing specifies Poland, Portugal, Hungary, Romania, or South Africa.",
        "Eligible work locations: Canada or Atlantis.",
    ],
)
def test_israel_header_cannot_resolve_a_conflicting_country_list(jd):
    result = decide_location_eligibility(
        {"location": "Israel", "raw_jd": jd}, None, PROFILE
    )
    assert result["eligibility"] == "unknown"
    assert result["eligibility_reason"].startswith("unresolved location restriction:")
    assert jd.rstrip(".") in result["eligibility_reason"]


@pytest.mark.parametrize("jd", [
    "This role is limited to Atlantis",
    "The role is restricted to Atlantis",
    "Atlantis-based applicants may apply",
    "המשרה מיועדת לאטלנטיס",
    "דרושים מועמדים מאטלנטיס",
    "Eligible work locations: Atlantis",
    "Eligible countries: US",
    "US residents only",
])
@pytest.mark.parametrize("lowercase", [False, True])
def test_new_frames_supply_positive_nonown_signals(jd, lowercase):
    assert decide_location_eligibility(
        {"location": "Tel Aviv", "raw_jd": jd.lower() if lowercase else jd},
        None, PROFILE,
    )["eligibility"] == "unknown"


@pytest.mark.parametrize("jd", [
    "This role is limited to Tel Aviv",
    "Tel Aviv-based applicants may apply",
    "המשרה מיועדת לתל אביב",
    "Eligible work locations: Tel Aviv",
    "German-speaking applicants may apply",
    "דרושים מועמדים דוברי גרמנית",
    "This role is limited to full-time work",
])
def test_new_frames_preserve_own_place_and_nonplace_controls(jd):
    assert decide_location_eligibility(
        {"location": "Tel Aviv", "raw_jd": jd}, None, PROFILE,
    )["eligibility"] == "eligible"


@pytest.mark.parametrize("jd", [
    "We welcome Israel-based candidates",
    "We are seeking Tel Aviv-based applicants",
    "We welcome Israel-based candidates with Python experience",
    "Applicants must be Israel-based candidates",
    "This role is limited to candidates with German-speaking skills",
    "This role is limited to experienced Python developers",
    "המשרה מיועדת למפתחי תוכנה",
    "דרושים מועמדים דוברי גרמנית עם ניסיון בפייתון",
    # Six variants of the review's own-place and qualification regressions.
    "We welcome Israeli candidates only",
    "המשרה מיועדת למועמדים מישראל",
    "This role is limited to candidates with fluent English",
    "This role is limited to Hebrew native level",
    "This role is limited to candidates with React-based experience",
    "This role is limited to cloud-based experience",
])
def test_prefixed_own_applicants_and_qualifications_are_not_foreign_scope(jd):
    from scraper.eligibility import _positive_nonown_signal

    assert decide_location_eligibility(
        {"location": "Tel Aviv", "raw_jd": jd}, None, PROFILE,
    )["eligibility"] == "eligible"
    assert not _positive_nonown_signal(jd, "Tel Aviv", "")


@pytest.mark.parametrize("jd,expected", [
    ("This role is limited to candidates from Israel with Python experience", "eligible"),
    ("We welcome German and Israel-based candidates", "unknown"),
    ("We welcome Germany and Israel-based candidates", "unknown"),
    ("דרושים מועמדים שמישראל", "eligible"),
    ("This role is limited to German native level", "eligible"),
    ("This role is limited to cloud-based", "eligible"),
])
def test_scope_slot_keeps_geography_separate_from_qualifications(jd, expected):
    assert decide_location_eligibility(
        {"location": "Tel Aviv", "raw_jd": jd}, None, PROFILE,
    )["eligibility"] == expected


@pytest.mark.parametrize("jd", [
    # R1: recruiting prose must not consume an unresolved list operand.
    "We welcome Atlantis and Israel-based candidates",
    "We welcome Atlantis or Israel-based candidates",
    "We are seeking New Atlantis and Tel Aviv-based applicants",
    "Applicants must be New Atlantis and Israel-based candidates",
    # R2: the base/from relation supplies context independently of word count.
    "We welcome Atlantis-based candidates",
    "This role is limited to candidates from Atlantis",
    "Israel and Atlantis-based applicants may apply",
    "We welcome New Atlantis-based candidates",
    "We are seeking New Atlantis-based applicants",
    "Applicants must be New Atlantis-based candidates",
    "This role is limited to candidates from New Atlantis",
    "The position is restricted to applicants located in New Atlantis",
    "This role is limited to candidates from Israel and Atlantis",
    "This role is limited to candidates from New Atlantis with Python experience",
    "We welcome Israel and New Atlantis-based candidates with German-speaking skills",
])
@pytest.mark.parametrize("lowercase", [False, True])
def test_explicit_unknown_applicant_destinations_preserve_complete_scope(jd, lowercase):
    from scraper.eligibility import _positive_nonown_signal

    jd = jd.lower() if lowercase else jd
    assert _positive_nonown_signal(jd, "Tel Aviv", "")
    result = decide_location_eligibility(
        {"location": "Tel Aviv", "raw_jd": jd}, None, PROFILE,
    )
    assert result["eligibility"] == "unknown"
    assert result["eligibility_reason"].startswith("unresolved location restriction:")


@pytest.mark.parametrize("jd", [
    "We are seeking Tel Aviv and Israel-based applicants",
    "Applicants must be Tel Aviv-based candidates",
    "This role is limited to candidates from Tel Aviv with Python experience",
    "The position is restricted to applicants located in Israel",
    "This role is limited to candidates with New Atlantis-based experience",
    "This role is limited to candidates with German native level",
    # P8G: generic fictional residency/credential labels have no positive signal.
    "Candidates must reside in Atlantis",
    "Quuxian applicants only",
    "Valid Atlantis work permit mandatory",
])
def test_unknown_scope_repair_preserves_own_qualification_and_p8g_controls(jd):
    from scraper.eligibility import _positive_nonown_signal

    assert not _positive_nonown_signal(jd, "Tel Aviv", "")
    assert decide_location_eligibility(
        {"location": "Tel Aviv", "raw_jd": jd}, None, PROFILE,
    )["eligibility"] == "eligible"
