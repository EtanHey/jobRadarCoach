from __future__ import annotations

import hashlib
import json

import pytest

from classifier.facts import Facts, link_status, normalize


@pytest.mark.parametrize(
    ("location", "countries", "regions", "cities"),
    [
        ("Tel Aviv-Yafo, Tel Aviv District, Israel", ["IL"], ["IL-TA"], ["Tel Aviv"]),
        ("Israel - Tel Aviv", ["IL"], ["IL-TA"], ["Tel Aviv"]),
        ("Austin, TX", ["US"], ["US-TX"], ["Austin"]),
        ("New York, NY", ["US"], ["US-NY"], ["New York"]),
        ("United States, NY", ["US"], ["US-NY"], []),
    ],
)
def test_location_aliases(location, countries, regions, cities):
    facts = normalize({"location": location, "title": "Engineer", "url": "https://example.test/job"})
    assert facts.countries == tuple(countries)
    assert facts.regions == tuple(regions)
    assert facts.cities == tuple(cities)


def test_multi_location_and_work_mode():
    facts = normalize({
        "location": "Tel Aviv, Israel / San Francisco, CA",
        "title": "Senior Engineer",
        "remote": True,
    })
    assert facts.countries == ("IL", "US")
    assert facts.regions == ("IL-TA", "US-CA")
    assert facts.cities == ("Tel Aviv", "San Francisco")
    assert facts.work_mode == "remote"


@pytest.mark.parametrize(
    ("posting", "expected"),
    [
        ({"location": "Remote - Israel"}, "remote"),
        ({"location": "Hybrid - Tel Aviv"}, "hybrid"),
        ({"location": "Tel Aviv", "remote": True}, "remote"),
        ({"location": "Tel Aviv", "remote": False}, "onsite"),
    ],
)
def test_work_mode(posting, expected):
    assert normalize(posting).work_mode == expected


def test_work_mode_only_location_is_not_unresolved():
    facts = normalize({"location": "Remote / Hybrid"})
    assert facts.work_mode == "remote"
    assert facts.unresolved_locations == ()


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("Intern", "intern"),
        ("Junior", "junior"),
        ("Mid-level", "mid"),
        ("Senior Software Engineer", "senior"),
        ("Staff Engineer", "staff_principal"),
        ("Principal Engineer", "staff_principal"),
        ("Lead Manager", "lead_manager"),
    ],
)
def test_seniority_buckets(value, expected):
    facts = normalize({"seniority": value, "title": "Intern Engineer"})
    assert facts.seniority_level == expected
    assert facts.seniority_source == "extracted"


def test_seniority_precedence_and_title_fallback():
    extracted = normalize({"seniority": "Junior", "title": "Senior Engineer"})
    title = normalize({"seniority": None, "title": "Staff Engineer"})
    assert (extracted.seniority_level, extracted.seniority_source) == ("junior", "extracted")
    assert (title.seniority_level, title.seniority_source) == ("staff_principal", "title")


def test_skills_use_stack_and_ui_aliases():
    facts = normalize({
        "stack": ["nodejs", "microsoft cloud"],
        "raw_jd": "Build with React Native, PostgreSQL, and Kubernetes.",
    })
    assert facts.skills_mentioned == ("Node.js", "Azure", "React Native", "PostgreSQL", "Kubernetes")


def test_skill_prose_guards_match_ui_aliases():
    facts = normalize({"raw_jd": "Python, Go, Rust. Please express interest this spring."})
    assert facts.skills_mentioned == ("Python", "Go", "Rust")


@pytest.mark.parametrize(
    ("raw_jd", "expected"),
    [
        ("skills:\nGo\nPython", ("Python", "Go")),
    ],
)
def test_skill_line_start_matches_ui_multiline_behavior(raw_jd, expected):
    assert normalize({"raw_jd": raw_jd}).skills_mentioned == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("HTTPS://example.test/job", "available"),
        ("https://[not-an-ip]/job", "invalid_url"),
        ("https://[::1]/job", "available"),
        ("https://example.test:0/job", "available"),
        ("https://example.test:65535/job", "available"),
        ("https://example.test:65536/job", "invalid_url"),
        ("https:///job", "invalid_url"),
        ("", "no_link"),
    ],
)
def test_link_status_parity(value, expected):
    assert link_status(value) == expected


def test_link_status_uses_url_when_apply_url_is_empty():
    assert normalize({"apply_url": "", "url": "https://example.test/job"}).link_status == "available"


def test_hash_is_sha256_of_canonical_normalized_output():
    facts = normalize({"location": "Tel Aviv, Israel", "title": "Engineer"})
    payload = facts.normalized_output()
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    assert facts.facts_sha256 == hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    assert isinstance(facts, Facts)
