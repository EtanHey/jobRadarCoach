from __future__ import annotations

from copy import deepcopy

import pytest

from classifier.facts import normalize
from extractor.core import extract_posting
from extractor.payload import build_payload
from extractor.test_core import RAW_JD, facts, posting, runner_for
from scraper.brain_contract import BrainValidationError


TITLE_CASES = [
    ("Senior Backend Engineer", "Senior", "senior"),
    ("Sr. Backend Engineer", "Sr.", "senior"),
    ("Lead Backend Engineer", "Lead", "lead_manager"),
    ("Staff Backend Engineer", "Staff", "staff_principal"),
    ("Principal Backend Engineer", "Principal", "staff_principal"),
    ("Junior Backend Engineer", "Junior", "junior"),
    ("מפתח בכיר", "בכיר", "senior"),
    ("מפתח ג'וניור", "ג'וניור", "junior"),
    ("מפתח ג׳וניור", "ג׳וניור", "junior"),
]


def test_generic_extraction_cannot_drop_senior_title_or_change_years_evidence():
    raw_jd = (
        "We are seeking a Software Engineer. You need 5+ years of software development "
        "experience. Build reliable automation and tools."
    )
    candidate = {key: {"value": None, "evidence_quote": None}
                 for key in ("location", "remote", "seniority", "salary")}
    candidate["stack"] = []
    candidate["seniority"] = {"value": "Software Engineer", "evidence_quote": "Software Engineer"}
    source = {**posting(raw_jd), "title": "Senior Software Engineer"}

    result = extract_posting(source, {}, runner=runner_for(candidate))

    assert result["facts"]["seniority"] == {
        "value": "Senior", "evidence_quote": "Senior Software Engineer",
    }
    assert source["raw_jd"] == raw_jd


@pytest.mark.parametrize(("title", "word", "level"), TITLE_CASES)
@pytest.mark.parametrize("inferred", [None, "Backend Engineer", "Senior"])
def test_explicit_title_wins_and_survives_payload_validation(title, word, level, inferred):
    source = {**posting(), "title": title}
    candidate = facts()
    candidate["seniority"] = {
        "value": inferred,
        "evidence_quote": "Senior Backend Engineer" if inferred else None,
    }
    original = deepcopy(candidate)

    result = extract_posting(source, {}, runner=runner_for(candidate))

    expected = {"value": word, "evidence_quote": title}
    assert result["facts"]["seniority"] == expected
    assert candidate == original
    assert build_payload(result, RAW_JD, posting_title=title).facts["seniority"] == expected
    normalized = normalize({"title": title, "seniority": inferred, "ats_seniority": "Mid"})
    assert (normalized.seniority_level, normalized.seniority_source) == (level, "title")


@pytest.mark.parametrize("title", ["Backend Engineer", "Seniority Analyst", "Staffing Engineer", "Leadership Engineer"])
def test_titles_without_explicit_level_preserve_extracted_evidence(title):
    candidate = facts()
    result = extract_posting({**posting(), "title": title}, {}, runner=runner_for(candidate))
    assert result["facts"]["seniority"] == candidate["seniority"]
    assert normalize({"title": title, "seniority": "Senior"}).seniority_source == "extracted"


def test_conflicting_title_levels_are_unknown_with_exact_remark():
    title = "Junior / Senior Backend Engineer"
    result = extract_posting({**posting(), "title": title}, {}, runner=runner_for(facts()))
    assert result["facts"]["seniority"] == {"value": None, "evidence_quote": None}
    assert result["facts"]["seniority_remark"] == title
    assert build_payload(result, RAW_JD, posting_title=title).facts == result["facts"]
    normalized = normalize({"title": title, "seniority": "Senior"})
    assert (normalized.seniority_level, normalized.seniority_source) == (None, "title")


@pytest.mark.parametrize(("title", "head"), [
    ("Senior Engineering Manager", "Manager"),
    ("Senior Manager, Platform Engineering", "Manager"),
    ("Sr. Software Engineering Manager", "Manager"),
    ("Senior Director of Platform Engineering", "Director"),
    ("Senior Head of Platform Engineering", "Head"),
])
def test_senior_modifier_keeps_explicit_management_head_noun(title, head):
    extracted = extract_posting({**posting(), "title": title}, {}, runner=runner_for(facts()))
    expected = {"value": head, "evidence_quote": title}
    assert extracted["facts"]["seniority"] == expected
    assert build_payload(extracted, RAW_JD, posting_title=title).facts["seniority"] == expected
    result = normalize({"title": title, "seniority": head})
    assert (result.seniority_level, result.seniority_source) == ("lead_manager", "title")


def test_title_cannot_supply_evidence_for_other_fields():
    candidate = facts()
    candidate["location"] = {"value": "Berlin", "evidence_quote": "Berlin"}
    with pytest.raises(BrainValidationError):
        # Title evidence is available only for the deterministic seniority fact.
        extract_posting({**posting(), "title": "Senior Engineer Berlin"}, {}, runner=runner_for(candidate))


FUNCTIONS = [
    "Program", "Product", "Project", "Account", "Marketing", "Partner",
    "Customer Success", "Delivery", "Platform", "Inventory",
    "Hardware Engineering Program", "Software Delivery", "Team Marketing",
]


@pytest.mark.parametrize("function", FUNCTIONS)
@pytest.mark.parametrize(("grade", "value", "level"), [
    ("Senior ", "Senior", "senior"), ("Staff ", "Staff", "staff_principal"),
    ("", None, None),
])
def test_function_manager_keeps_grade_or_abstains(function, grade, value, level):
    title = f"{grade}{function} Manager"
    extracted = extract_posting({**posting(), "title": title}, {}, runner=runner_for(facts()))
    expected = {"value": value, "evidence_quote": title if value else None}
    assert extracted["facts"]["seniority"] == expected
    assert build_payload(extracted, RAW_JD, posting_title=title).facts["seniority"] == expected
    normalized = normalize({"title": title, "seniority": "Manager", "ats_seniority": "Manager"})
    assert (normalized.seniority_level, normalized.seniority_source) == (level, "title")


@pytest.mark.parametrize(("role", "head"), [
    ("Engineering Manager", "Manager"), ("Software Engineering Manager", "Manager"),
    ("Software Manager", "Manager"), ("R&D Manager", "Manager"),
    ("Development Manager", "Manager"), ("Team Manager", "Manager"),
    ("Group Manager", "Manager"), ("Developer Relations Manager", "Manager"),
    ("Cloud Engineering Build Manager", "Manager"),
    ("Head of Infrastructure", "Head"),
    ("Director of Operations", "Director"), ("VP of Engineering", "VP"),
    ("ראש צוות", "ראש צוות"), ("מנהל פיתוח", "מנהל פיתוח"),
])
@pytest.mark.parametrize("grade", ["", "Senior "])
def test_people_management_heads_keep_management_grade(role, head, grade):
    title = grade + role
    extracted = extract_posting({**posting(), "title": title}, {}, runner=runner_for(facts()))
    expected = {"value": head, "evidence_quote": title}
    assert extracted["facts"]["seniority"] == expected
    assert build_payload(extracted, RAW_JD, posting_title=title).facts["seniority"] == expected
    assert normalize({"title": title}).seniority_level == "lead_manager"
