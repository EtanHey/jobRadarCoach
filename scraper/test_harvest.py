#!/usr/bin/env python3
"""Tests for the credential-free LinkedIn job-feed harvester."""

import importlib.util
import json
import os
import signal
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.parse import parse_qs, urlparse

import pytest
from pathlib import Path


HERE = Path(__file__).resolve().parent
HARVEST_PATH = HERE / "harvest.py"
FIXTURE_PATH = HERE / "fixtures" / "linkedin-search-2026-08-09.html"
JD_FIXTURE_PATH = HERE / "fixtures" / "linkedin-job-4450949378-2026-08-09.html"
FEED_FIXTURE_PATH = HERE / "fixtures" / "job-feed-2026-08-10.jsonl"
ROUND4_RESCORE_FIXTURE_PATH = HERE / "fixtures" / "job-radar-rescore-2026-08-11.json"
RESCORE_SCRIPT_PATH = HERE / "rescore_fixture.py"
SEARCHES_PATH = HERE / "searches.yaml"
PROFILE_PATH = HERE.parent / "profile.example.yaml"
ROLE_TYPE_HITS = {
    "data-scientist", "algorithm-engineer", "ml-engineer",
    "research-engineer", "computer-vision", "nlp-researcher",
    "qa-only", "team-lead", "engineering-manager", "tech-lead",
}


def load_harvest_module():
    spec = importlib.util.spec_from_file_location("job_feed_harvest", HARVEST_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def phase2_annotation(fit_score: int) -> dict[str, object]:
    evidence_id = "posting:test"
    return {
        "employer_type": "direct",
        "seniority_real": False,
        "fit_score": fit_score,
        "fit_tier": "strong" if fit_score >= 80 else "good",
        "recommendation": "apply",
        "reasons": [
            {
                "factor": factor,
                "basis": "comparison",
                "assessment": "positive",
                "evidence_ids": [evidence_id],
                "detail": f"Evidence for {factor}.",
            }
            for factor in (
                "product_role_match", "stack_domain_evidence", "seniority_gap",
                "employer_type", "preferences",
            )
        ],
        "fit_line": f"Fit score {fit_score} from verified evidence.",
        "fit_line_evidence_ids": [evidence_id, "profile:preferences"],
        "luna_status": "ok",
    }


def test_harvest_module_exists() -> None:
    assert HARVEST_PATH.is_file(), "harvest.py must provide the scheduled job-feed entry point"


def test_parse_saved_linkedin_guest_fixture() -> None:
    harvest = load_harvest_module()
    postings = harvest.parse_job_cards(FIXTURE_PATH.read_text(encoding="utf-8"))

    assert postings == [
        {
            "id": "4449293792",
            "title": "Full Stack Engineer",
            "company": "Gotfriends",
            "location": "Tel Aviv District, Israel",
            "url": "https://il.linkedin.com/jobs/view/full-stack-engineer-at-gotfriends-4449293792",
            "posted_ago": "1 hour ago",
            "raw_text": "Full Stack Engineer Gotfriends Tel Aviv District, Israel Be an early applicant 1 hour ago",
        },
        {
            "id": "4449288878",
            "title": "Full Stack Next.js Developer, Customer-Facing Web (AI-First)",
            "company": "Bridgify",
            "location": "Tel Aviv-Yafo, Tel Aviv District, Israel",
            "url": "https://il.linkedin.com/jobs/view/full-stack-next-js-developer-customer-facing-web-ai-first-at-bridgify-4449288878",
            "posted_ago": "1 hour ago",
            "raw_text": "Full Stack Next.js Developer, Customer-Facing Web (AI-First) Bridgify Tel Aviv-Yafo, Tel Aviv District, Israel Be an early applicant 1 hour ago",
        },
    ]


def test_parse_saved_linkedin_guest_job_description_fixture() -> None:
    harvest = load_harvest_module()
    fixture = JD_FIXTURE_PATH.read_text(encoding="utf-8")
    assert "See who abra has hired for this role" in fixture
    assert "Seniority level" in fixture

    description = harvest.parse_job_description(fixture)

    assert description is not None
    assert description.startswith(
        "abra professional services is seeking a talented Full Stack Developer"
    )
    assert "Proven experience with C# .NET – Mandatory" in description
    assert "Experience with AngularJS – Advantage" in description
    assert "show-more-less-html" not in description
    assert "See who abra has hired for this role" not in description
    assert "Seniority level" not in description


@pytest.mark.parametrize(
    (
        "text",
        "expected_positive",
        "expected_senior",
        "expected_keywords",
        "expected_negative_hits",
    ),
    [
        ("Full Stack Next.js Engineer using React, TypeScript and Node", True, False, {"full-stack", "next.js", "react", "typescript", "node"}, set()),
        ("Senior Frontend Engineer, React and TypeScript", True, True, {"react", "typescript"}, set()),
        ("Principal Embedded C++ Engineer", False, True, set(), {"principal", "embedded", "c++"}),
        ("Staff Backend Engineer, Java-only platform", False, True, set(), {"staff", "java-only"}),
        ("QA Automation Engineer, QA-only role", False, False, set(), {"qa-only"}),
        ("AI Engineer building LLM agents and MCP services", False, False, {"ai", "llm", "agents", "mcp"}, set()),
        ("Software Engineer, 10+ years required", False, False, set(), {"10+ years"}),
    ],
)
def test_score_posting_rules(
    text: str,
    expected_positive: bool,
    expected_senior: bool,
    expected_keywords: set[str],
    expected_negative_hits: set[str],
) -> None:
    harvest = load_harvest_module()
    scored = harvest.score_posting({"title": text, "raw_text": text})

    assert (scored["score"] > 0) is expected_positive
    assert scored["senior_titled"] is expected_senior
    assert expected_keywords <= set(scored["matched_keywords"])
    assert set(scored["negative_hits"]) == expected_negative_hits


def test_ai_bonuses_preserve_gated_keyword_evidence() -> None:
    harvest = load_harvest_module()

    ai_only = harvest.score_posting(
        {
            "title": "AI Engineer",
            "jd_text": "Build GenAI LLM agents and MCP services",
            "jd_fetched": True,
        }
    )
    core_plus_ai = harvest.score_posting(
        {
            "title": "Frontend Software Engineer",
            "jd_text": "Build a React TypeScript product with GenAI LLM agents",
            "jd_fetched": True,
        }
    )

    assert ai_only["score"] == 0
    assert {"ai", "genai", "llm", "agents", "mcp"} <= set(
        ai_only["matched_keywords"]
    )
    assert ai_only["core_stack_present"] is False
    assert ai_only["ai_bonus_gated"] is True
    assert core_plus_ai["score"] > 0
    assert {"react", "typescript", "genai", "llm", "agents"} <= set(
        core_plus_ai["matched_keywords"]
    )
    assert core_plus_ai["core_stack_present"] is True
    assert core_plus_ai["ai_bonus_gated"] is False


@pytest.mark.parametrize(
    "core_signal",
    ["TypeScript", "React", "Next.js", "Node.js", "full-stack", "frontend"],
)
def test_each_core_stack_signal_unlocks_ai_bonus(core_signal: str) -> None:
    harvest = load_harvest_module()

    scored = harvest.score_posting(
        {
            "title": "Software Engineer",
            "jd_text": f"Build a {core_signal} product using AI and LLMs",
            "jd_fetched": True,
        }
    )

    assert scored["score"] > 0
    assert scored["core_stack_present"] is True
    assert scored["ai_bonus_gated"] is False
    assert {"ai", "llm"} <= set(scored["matched_keywords"])


@pytest.mark.parametrize(
    ("role_text", "expected_hit"),
    [
        ("Data Scientist", "data-scientist"),
        ("Algorithm Engineer", "algorithm-engineer"),
        ("ML Engineer", "ml-engineer"),
        ("Research Engineer", "research-engineer"),
        ("Computer Vision Engineer", "computer-vision"),
        ("NLP Researcher", "nlp-researcher"),
        ("Quality Engineer", "qa-only"),
        ("QA Automation Engineer", "qa-only"),
        ("Team Leader", "team-lead"),
        ("Engineering Manager", "engineering-manager"),
        ("Tech Lead", "tech-lead"),
    ],
)
def test_non_target_role_types_are_title_only_negatives(
    role_text: str, expected_hit: str
) -> None:
    harvest = load_harvest_module()

    title_scored = harvest.score_posting({"title": role_text, "raw_text": role_text})
    jd_scored = harvest.score_posting(
        {
            "title": "Software Engineer",
            "jd_text": f"This {role_text} role uses TypeScript, React, AI and LLMs.",
            "jd_fetched": True,
        }
    )

    assert title_scored["score"] <= 0
    assert expected_hit in title_scored["negative_hits"]
    assert jd_scored["score"] > 0
    assert expected_hit not in jd_scored["negative_hits"]


@pytest.mark.parametrize(
    ("role_text", "expected_hit"),
    [
        ("Part-Time Full Stack Engineer", "part-time"),
        ("Student Software Engineer", "student"),
        ("Frontend Engineering Intern", "intern"),
    ],
)
def test_non_full_time_training_titles_are_strong_title_only_negatives(
    role_text: str, expected_hit: str
) -> None:
    harvest = load_harvest_module()

    title_scored = harvest.score_posting(
        {
            "title": role_text,
            "jd_text": "TypeScript React Node.js full-stack AI LLM agents",
            "jd_fetched": True,
        }
    )
    jd_scored = harvest.score_posting(
        {
            "title": "Software Engineer",
            "jd_text": f"Mentor a {role_text} while building React and TypeScript products",
            "jd_fetched": True,
        }
    )

    assert title_scored["score_title"] <= 0
    assert expected_hit in title_scored["negative_hits"]
    assert jd_scored["score"] > 0
    assert expected_hit not in jd_scored["negative_hits"]


@pytest.mark.parametrize(
    ("title", "jd_text", "expected_positive", "expected_negative_hit"),
    [
        (
            "Frontend Software Engineer",
            "TypeScript React full-stack frontend product engineering",
            True,
            None,
        ),
        ("Data Scientist (37241)", "GenAI AI LLM modeling", False, "data-scientist"),
        (
            "Core Backend Quality Engineer",
            "TypeScript AI platform testing",
            False,
            "qa-only",
        ),
        ("Algorithm Engineer", "AI agents research", False, "algorithm-engineer"),
        (
            "AI Algorithm Team Leader",
            "AI LLM research leadership",
            False,
            "team-lead",
        ),
        (
            "Back End Developer",
            "React Node frontend product development",
            True,
            None,
        ),
    ],
)
def test_live_2026_08_10_role_controls(
    title: str,
    jd_text: str,
    expected_positive: bool,
    expected_negative_hit: str | None,
) -> None:
    harvest = load_harvest_module()

    scored = harvest.score_posting(
        {"title": title, "jd_text": jd_text, "jd_fetched": True}
    )

    assert (scored["score"] > 0) is expected_positive
    if expected_negative_hit is not None:
        assert expected_negative_hit in scored["negative_hits"]


def test_quality_role_receives_only_one_category_penalty() -> None:
    harvest = load_harvest_module()

    scored = harvest.score_posting(
        {
            "title": "QA Automation Quality Engineer",
            "jd_text": "TypeScript React AI LLM",
            "jd_fetched": True,
        }
    )

    assert scored["negative_hits"].count("qa-only") == 1


@pytest.mark.parametrize(
    ("title", "jd_text"),
    [
        (
            "Full Stack Engineer",
            "TypeScript React Node full-stack role reporting to the Tech Lead "
            "and Engineering Manager",
        ),
        (
            "Backend Developer",
            "Node service where our team leader runs weekly design reviews",
        ),
        (
            "Frontend Engineer",
            "React TypeScript role partnering with QA engineers on quality assurance",
        ),
    ],
)
def test_jd_role_boilerplate_does_not_penalize_valid_ic_roles(
    title: str, jd_text: str
) -> None:
    harvest = load_harvest_module()

    scored = harvest.score_posting(
        {"title": title, "jd_text": jd_text, "jd_fetched": True}
    )

    assert scored["score"] > 0
    assert ROLE_TYPE_HITS.isdisjoint(scored["negative_hits"])


def test_multiple_role_type_title_hits_apply_one_penalty() -> None:
    harvest = load_harvest_module()

    scored = harvest.score_posting(
        {"title": "Tech Lead / Engineering Manager", "raw_text": ""}
    )

    assert scored["score"] == -12
    assert {"tech-lead", "engineering-manager"} <= set(scored["negative_hits"])


def test_rescore_gates_ai_profile_fit_bonus_without_core_stack() -> None:
    harvest = load_harvest_module()

    rescored = harvest.rescore_stored_posting(
        {
            "title": "AI Engineer",
            "score": 1,
            "matched_keywords": ["ai-engineer"],
            "negative_hits": [],
        }
    )

    assert rescored["score"] == 0
    assert rescored["ai_bonus_gated"] is True


def test_rescore_does_not_duplicate_an_existing_role_type_penalty() -> None:
    harvest = load_harvest_module()

    rescored = harvest.rescore_stored_posting(
        {
            "title": "Tech Lead / Team Lead",
            "score": -12,
            "matched_keywords": [],
            "negative_hits": ["team-lead"],
        }
    )

    assert rescored["score"] == -12
    assert {"team-lead", "tech-lead"} <= set(rescored["negative_hits"])


def test_real_2026_08_10_snapshot_rescores_with_upwind_first() -> None:
    harvest = load_harvest_module()
    before = [
        json.loads(line)
        for line in FEED_FIXTURE_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    after = [harvest.rescore_stored_posting(posting) for posting in before]
    ranked = sorted(after, key=lambda posting: -int(posting["score"]))
    by_title = {str(posting["title"]): posting for posting in after}

    assert ranked[0]["title"] == "Frontend Software Engineer"
    assert by_title["Frontend Software Engineer"]["score"] == 12
    assert by_title["Back End Developer"]["score"] > 0
    assert by_title["Core Backend Quality Engineer"]["score"] <= 0
    assert by_title["Data Scientist (37241)"]["score"] <= 0
    assert by_title["Algorithm Engineer"]["score"] <= 0
    assert by_title["AI Algorithm Team Leader"]["score"] <= 0

    table = harvest.format_rescore_table(before, after)
    assert "| 12 | 12 | Frontend Software Engineer |" in table
    assert "| 8 | -12 | Data Scientist (37241) | data-scientist |" in table


def test_round4_named_jd_fixture_reproduces_reported_score_boundaries() -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(RESCORE_SCRIPT_PATH),
            "--fixture",
            str(ROUND4_RESCORE_FIXTURE_PATH),
            "--profile",
            str(PROFILE_PATH),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "| 17 | -23 | Full Stack Developer - JB-731 |" in result.stdout
    assert "| 15 | -1 | Senior Backend Engineer |" in result.stdout
    assert "| 10 | 10 | Full Stack Developer (React / Next.js / Node.js) |" in result.stdout
    assert "| 10 | 10 | Forward Deployed Engineer, Data & AI |" in result.stdout
    assert "| 13 | 13 | Full Stack Engineer |" in result.stdout


def test_infra_requirement_keeps_context_across_eg_parenthetical() -> None:
    harvest = load_harvest_module()

    assert harvest._score_requirement_walls(
        "Strong familiarity with Infrastructure as Code (e.g., Terraform)."
    ) == [("infra:terraform", -8)]


def test_infra_or_list_of_only_wall_technologies_is_not_exempt() -> None:
    harvest = load_harvest_module()

    assert harvest._score_requirement_walls(
        "Requirements: Experience with Docker, Kubernetes, or Terraform."
    ) == [
        ("infra:docker", -8),
        ("infra:kubernetes", -8),
        ("infra:terraform", -8),
    ]


def test_infra_or_list_with_claimable_named_alternative_is_exempt() -> None:
    harvest = load_harvest_module()

    assert harvest._score_requirement_walls(
        "Requirements: Experience with Docker, Kubernetes, or AWS."
    ) == []


def test_python_primary_wording_outweighs_an_earlier_language_or_list() -> None:
    harvest = load_harvest_module()

    assert harvest._score_requirement_walls(
        "Requirements: Experience with Java, Python, or Go, and deep proficiency "
        "in Python is required."
    ) == [("python-primary", -16)]


def test_k8s_alias_is_an_infra_wall() -> None:
    harvest = load_harvest_module()

    assert harvest._score_requirement_walls(
        "Requirements: hands-on experience with K8s and Docker."
    ) == [("infra:docker", -8), ("infra:kubernetes", -8)]


@pytest.mark.parametrize(
    ("requirement", "label", "expected_weight"),
    [
        ("C# required", "c#", -8),
        ("ASP.NET required", ".net", -8),
        ("AngularJS required", "angular", -6),
        ("Vue.js required", "vue", -6),
        ("Semiconductor EDA background", "semiconductor/eda", -10),
        ("Hardware verification", "verification", -6),
        ("React Native experience", "react-native", -1),
        ("8+ years required", "8-9+ years", -10),
        ("6+ years required", "5-7+ years", -4),
    ],
)
def test_live_triage_negative_rules(
    requirement: str, label: str, expected_weight: int
) -> None:
    harvest = load_harvest_module()

    scored = harvest.score_posting({"title": requirement, "raw_text": requirement})

    assert scored["score"] == expected_weight
    assert scored["negative_hits"] == [label]


def test_full_description_turns_clean_abra_title_negative() -> None:
    harvest = load_harvest_module()
    description = harvest.parse_job_description(
        JD_FIXTURE_PATH.read_text(encoding="utf-8")
    )
    assert description is not None

    scored = harvest.score_posting(
        {
            "title": "Full Stack Developer",
            "raw_text": "Full Stack Developer abra Center District, Israel",
            "jd_text": description,
            "jd_fetched": True,
        }
    )

    assert scored["score_title"] == 4
    assert scored["score"] < 0
    assert {"c#", ".net"} <= set(scored["negative_hits"])
    assert "angular" not in scored["negative_hits"]
    assert "full-stack" in scored["matched_keywords"]


def test_react_or_vue_alternative_does_not_trigger_vue_negative() -> None:
    harvest = load_harvest_module()

    scored = harvest.score_posting(
        {
            "title": "Full Stack Engineer",
            "jd_text": (
                "Minimum 5 years of experience on the Frontend using "
                "React (or Vue.js) – Mandatory"
            ),
            "jd_fetched": True,
        }
    )

    assert "react" in scored["matched_keywords"]
    assert "vue" not in scored["negative_hits"]
    assert "5-7+ years" in scored["negative_hits"]


def test_example_list_with_core_term_waives_negative_term() -> None:
    """Singular JD (2026-08-19 false flag): 'frameworks such as React, Angular,
    Vue.js' is an illustrative list that includes the core stack — Angular must
    not be penalized, but the waiver is traced rather than silently dropped."""
    harvest = load_harvest_module()

    scored = harvest.score_posting(
        {
            "title": "Senior Full-Stack Engineer",
            "jd_text": (
                "You'll build our frontend using frameworks such as React, "
                "Angular, Vue.js depending on the service."
            ),
            "jd_fetched": True,
        }
    )

    assert "react" in scored["matched_keywords"]
    assert "angular" not in scored["negative_hits"]
    assert "angular(example-list, waived)" in scored["negative_hits"]


def test_angular_without_example_marker_still_penalized() -> None:
    """No example marker introduces the mention — the negative still counts."""
    harvest = load_harvest_module()

    scored = harvest.score_posting(
        {
            "title": "Frontend Engineer",
            "jd_text": "You must have deep Angular experience shipping production apps.",
            "jd_fetched": True,
        }
    )

    assert scored["negative_hits"] == ["angular"]
    assert scored["score"] == -6


def test_example_list_waiver_does_not_suppress_a_separate_standalone_mention() -> None:
    """Waived inside the illustrative list, but a second, standalone mention
    outside any example list still counts per the brief — and, since the two
    occurrences resolve differently, the trace records BOTH: the real penalty
    AND why the other occurrence didn't add to it."""
    harvest = load_harvest_module()

    scored = harvest.score_posting(
        {
            "title": "Senior Full-Stack Engineer",
            "jd_text": (
                "Frameworks such as React, Angular, Vue.js are common frontend "
                "options here. This particular team runs a very different "
                "playbook from the rest of engineering, and every new hire on "
                "this specific pod must have deep Angular experience before "
                "they touch the shared component library."
            ),
            "jd_fetched": True,
        }
    )

    assert "angular" in scored["negative_hits"]
    assert "angular(example-list, waived)" in scored["negative_hits"]


def test_example_list_waiver_scoped_to_enumeration_not_whole_sentence() -> None:
    """CodeRabbit round-1 finding: a second Angular mention later in the SAME
    sentence, past the enumeration (here past 'are supported, but'), is a real
    requirement and must not ride the earlier list's waiver — exercised directly
    against the per-occurrence helper so the assertion isn't confounded by the
    separate, pre-existing `_is_non_required_stack_context` heuristic."""
    harvest = load_harvest_module()

    text = (
        "Frameworks such as React, Angular, and Vue are supported, but "
        "deep Angular experience is required."
    )
    # A missing named rule must fail the test loudly.
    pattern = next(  # skipcq: PTC-W0063
        pattern for label, pattern, _weight, _scope in harvest.NEGATIVE_RULES
        if label == "angular"
    )
    occurrences = list(pattern.finditer(text))
    assert len(occurrences) == 2

    assert harvest._is_example_list_occurrence(text, occurrences[0]) is True
    assert harvest._is_example_list_occurrence(text, occurrences[1]) is False


def test_example_list_waiver_survives_internal_period_in_core_term() -> None:
    """CodeRabbit round-1 finding: 'React.js' has an internal period — the
    sentence-boundary heuristic must not split there and lose the marker/core-term
    context for a later item in the same list."""
    harvest = load_harvest_module()

    text = "We use frameworks such as React.js, Angular, and Vue for the frontend."
    # A missing named rule must fail the test loudly.
    pattern = next(  # skipcq: PTC-W0063
        pattern for label, pattern, _weight, _scope in harvest.NEGATIVE_RULES
        if label == "angular"
    )
    occurrence = pattern.search(text)
    assert occurrence is not None

    assert harvest._is_example_list_occurrence(text, occurrence) is True


def test_example_list_marker_survives_eg_abbreviation() -> None:
    """CodeRabbit round-2 finding: 'e.g.' ends in punctuation followed by a
    capitalized word — the sentence-boundary heuristic must not treat that
    period as a sentence end and strand 'e.g.' outside the term's fragment."""
    harvest = load_harvest_module()

    text = "The stack includes e.g. React, Angular, and Vue for the frontend layer."
    # A missing named rule must fail the test loudly.
    pattern = next(  # skipcq: PTC-W0063
        pattern for label, pattern, _weight, _scope in harvest.NEGATIVE_RULES
        if label == "angular"
    )
    occurrence = pattern.search(text)
    assert occurrence is not None

    assert harvest._is_example_list_occurrence(text, occurrence) is True


def test_example_list_trace_recorded_alongside_a_live_hit_for_same_label() -> None:
    """CodeRabbit round-2 finding: when one occurrence of a label is live and
    another is waived, both facts must be traced — not just the live one."""
    harvest = load_harvest_module()

    scored = harvest.score_posting(
        {
            "title": "",
            "jd_text": (
                "Frameworks such as React, Angular, Vue support the frontend. "
                "This pod specifically expects deep Angular experience before "
                "you touch production code across the whole platform."
            ),
            "jd_fetched": True,
        }
    )

    assert "angular" in scored["negative_hits"]
    assert "angular(example-list, waived)" in scored["negative_hits"]


def test_would_like_verb_phrase_is_not_an_example_list_marker() -> None:
    """CodeRabbit round-3 finding: 'like' is also a common verb ('we would
    like C++ engineers with React experience') — that must not read as a
    list-introducing preposition and waive a real required term."""
    harvest = load_harvest_module()

    text = "We would like C++ engineers with React experience."
    # A missing named rule must fail the test loudly.
    pattern = next(  # skipcq: PTC-W0063
        pattern for label, pattern, _weight, _scope in harvest.NEGATIVE_RULES
        if label == "c++"
    )
    occurrence = pattern.search(text)
    assert occurrence is not None

    assert harvest._is_example_list_occurrence(text, occurrence) is False


def test_like_as_a_real_list_marker_still_waives() -> None:
    """Sanity check for the fix above: 'technologies like X, Y, Z' — a genuine
    list-introducing 'like' — still waives a non-core term inside it."""
    harvest = load_harvest_module()

    scored = harvest.score_posting(
        {
            "title": "",
            "jd_text": (
                "We use technologies like React, Angular, and Vue on the frontend."
            ),
            "jd_fetched": True,
        }
    )

    assert "angular" not in scored["negative_hits"]
    assert "angular(example-list, waived)" in scored["negative_hits"]


def test_like_as_a_verb_does_not_waive_without_would() -> None:
    """Bugbot: 'like' is a verb in 'we like C++ engineers with React' even
    without the 'would like' spelling — that is not an example list."""
    harvest = load_harvest_module()

    text = "We like C++ engineers with React experience."
    # A missing named rule must fail the test loudly.
    pattern = next(  # skipcq: PTC-W0063
        pattern for label, pattern, _weight, _scope in harvest.NEGATIVE_RULES
        if label == "c++"
    )
    occurrence = pattern.search(text)
    assert occurrence is not None
    assert harvest._is_example_list_occurrence(text, occurrence) is False


def test_hebrew_or_connector_does_not_steal_example_marker() -> None:
    """Bugbot: Hebrew 'או' is 'or', a list connector. Using it as a marker made
    the last או steal the list so the CORE term sat *before* the marker and
    Angular/Vue after 'כמו React או …' were not waived."""
    harvest = load_harvest_module()

    text = "עובדים עם טכנולוגיות כמו React או Angular בפרונט."
    # A missing named rule must fail the test loudly.
    angular = next(  # skipcq: PTC-W0063
        pattern for label, pattern, _weight, _scope in harvest.NEGATIVE_RULES
        if label == "angular"
    )
    occurrence = angular.search(text)
    assert occurrence is not None
    assert harvest._is_example_list_occurrence(text, occurrence) is True

    scored = harvest.score_posting(
        {
            "title": "Full-Stack Engineer",
            "jd_text": "מסגרות כגון React, Angular או Vue.js",
            "jd_fetched": True,
        }
    )
    assert "angular" not in scored["negative_hits"]
    assert "vue" not in scored["negative_hits"]
    assert "angular(example-list, waived)" in scored["negative_hits"]
    assert "vue(example-list, waived)" in scored["negative_hits"]


def test_one_of_our_is_not_an_example_list_marker() -> None:
    """Bugbot: 'one of our Angular developers also uses React' is a real
    Angular requirement — 'one of' here is not introducing a tech enumeration."""
    harvest = load_harvest_module()

    text = "one of our Angular developers also uses React daily."
    # A missing named rule must fail the test loudly.
    pattern = next(  # skipcq: PTC-W0063
        pattern for label, pattern, _weight, _scope in harvest.NEGATIVE_RULES
        if label == "angular"
    )
    occurrence = pattern.search(text)
    assert occurrence is not None
    assert harvest._is_example_list_occurrence(text, occurrence) is False


def test_core_in_same_clause_is_not_enough_without_list_sibling() -> None:
    """Bugbot: a CORE term later in the clause ('including React and then
    Angular experience is mandatory') must not waive a separately-required
    negative term that is not a list sibling of that CORE term."""
    harvest = load_harvest_module()

    text = "including React and then Angular experience is mandatory"
    # A missing named rule must fail the test loudly.
    pattern = next(  # skipcq: PTC-W0063
        pattern for label, pattern, _weight, _scope in harvest.NEGATIVE_RULES
        if label == "angular"
    )
    occurrence = pattern.search(text)
    assert occurrence is not None
    assert harvest._is_example_list_occurrence(text, occurrence) is False


@pytest.mark.parametrize(
    ("job_id", "requirement", "expected_positive"),
    [
        (
            "4451332413",
            "Experience in TypeScript, Node.js, Python, C#, or similar languages",
            {"typescript", "node"},
        ),
        (
            "4440135525",
            "Modern web development frameworks, C#, Java, or equivalent",
            set(),
        ),
        (
            "4414695272",
            "Java, Python, Scala C#, Go, Node.JS and C++",
            {"node"},
        ),
    ],
)
def test_polyglot_alternative_list_does_not_trigger_stack_negative(
    job_id: str, requirement: str, expected_positive: set[str]
) -> None:
    harvest = load_harvest_module()

    scored = harvest.score_posting(
        {
            "id": job_id,
            "title": "Backend Software Engineer",
            "jd_text": requirement,
            "jd_fetched": True,
        }
    )

    assert expected_positive <= set(scored["matched_keywords"])
    assert {"c#", "c++"}.isdisjoint(scored["negative_hits"])


def test_body_boilerplate_does_not_trigger_title_or_hardware_rules() -> None:
    harvest = load_harvest_module()

    scored = harvest.score_posting(
        {
            "title": "Software Engineer",
            "raw_text": "Software Engineer Example Co",
            "jd_text": (
                "Act as principal point of contact for our staff, embedded in the "
                "product team after background verification."
            ),
            "jd_fetched": True,
        }
    )

    assert scored["negative_hits"] == []


@pytest.mark.parametrize(
    "requirement",
    [
        "8 years of experience",
        "9+ years of experience",
        "8-10 years of experience",
        "at least 8 years of experience",
        "minimum of 9 years of experience",
    ],
)
def test_high_year_requirements_match_common_jd_phrasings(requirement: str) -> None:
    harvest = load_harvest_module()

    scored = harvest.score_posting(
        {
            "title": "Software Engineer",
            "jd_text": requirement,
            "jd_fetched": True,
        }
    )

    assert scored["negative_hits"] == ["8-9+ years"]


@pytest.mark.parametrize(
    ("requirement", "expected_hit"),
    [
        ("6-10 years of experience", "5-7+ years"),
        ("10-12 years of experience", "10+ years"),
        ("at least 10 years of experience", "10+ years"),
    ],
)
def test_year_range_receives_one_lower_bound_penalty(
    requirement: str, expected_hit: str
) -> None:
    harvest = load_harvest_module()

    scored = harvest.score_posting(
        {
            "title": "Software Engineer",
            "jd_text": requirement,
            "jd_fetched": True,
        }
    )

    assert scored["negative_hits"] == [expected_hit]


def test_seniority_rule_still_applies_to_title() -> None:
    harvest = load_harvest_module()

    scored = harvest.score_posting(
        {
            "title": "Principal Software Engineer",
            "jd_text": "Build a React platform",
            "jd_fetched": True,
        }
    )

    assert "principal" in scored["negative_hits"]


def test_blocked_jd_falls_back_to_title_only_score() -> None:
    harvest = load_harvest_module()
    postings, warning_count = harvest.fetch_job_descriptions(
        [
            {
                "id": "blocked-1",
                "title": "Full Stack Developer",
                "raw_text": "Full Stack Developer C# from card noise",
                "url": "https://www.linkedin.com/jobs/view/blocked-1",
                "jd_text": "Short existing description",
                "jd_chars": 26,
            }
        ],
        fetcher=lambda _url: {
            "jd_text": "",
            "jd_chars": 0,
            "fetch_method": "failed",
            "fetch_error": "blocked",
        },
        sleep=lambda _seconds: None,
    )

    scored = harvest.score_posting(postings[0])

    assert warning_count == 1
    assert postings[0]["jd_fetched"] is False
    assert postings[0]["fetch_method"] == "failed"
    assert postings[0]["jd_chars"] == 0
    assert scored["score_title"] == 4
    assert scored["score"] == 4
    assert scored["negative_hits"] == []


def test_successful_jd_fetch_uses_the_original_public_posting_url() -> None:
    harvest = load_harvest_module()
    requested_urls: list[str] = []
    description = "React TypeScript full-stack product work. " * 8

    def fetcher(url: str) -> dict[str, object]:
        requested_urls.append(url)
        return {
            "jd_text": description,
            "jd_chars": len(description),
            "fetch_method": "guest-html",
            "fetch_error": None,
        }

    postings, warning_count = harvest.fetch_job_descriptions(
        [
            {
                "id": "4450949378",
                "title": "Full Stack Developer",
                "url": "https://il.linkedin.com/jobs/view/full-stack-developer-at-abra-4450949378",
            }
        ],
        fetcher=fetcher,
        sleep=lambda _seconds: None,
    )

    assert warning_count == 0
    assert requested_urls == [
        "https://il.linkedin.com/jobs/view/full-stack-developer-at-abra-4450949378"
    ]
    assert postings[0]["jd_fetched"] is True
    assert postings[0]["fetch_method"] == "guest-html"
    assert postings[0]["jd_text"] == description


def test_jd_fetch_triggers_below_200_chars_paces_and_honors_cap() -> None:
    harvest = load_harvest_module()
    requested_urls: list[str] = []
    sleeps: list[float] = []
    fetched_text = "React TypeScript full-stack product work. " * 8
    postings = [
        {"id": "1", "url": "https://example.test/jobs/view/1", "jd_text": ""},
        {"id": "2", "url": "https://example.test/jobs/view/2", "jd_text": "short"},
        {"id": "3", "url": "https://example.test/jobs/view/3", "jd_text": ""},
        {
            "id": "4",
            "url": "https://example.test/jobs/view/4",
            "jd_text": "x" * 200,
            "jd_fetched": True,
        },
        {
            "id": "ats-1",
            "source": "greenhouse",
            "url": "https://example.test/ats/1",
            "jd_text": "",
        },
    ]

    def fetcher(url: str) -> dict[str, object]:
        requested_urls.append(url)
        return {
            "jd_text": fetched_text,
            "jd_chars": len(fetched_text),
            "fetch_method": "guest-html",
            "fetch_error": None,
        }

    enriched, warnings = harvest.fetch_job_descriptions(
        postings,
        fetcher=fetcher,
        sleep=sleeps.append,
        max_fetches=2,
    )

    assert warnings == 0
    assert requested_urls == [
        "https://example.test/jobs/view/1",
        "https://example.test/jobs/view/2",
    ]
    assert sleeps == [2.0]
    assert [posting.get("jd_fetched") for posting in enriched] == [
        True,
        True,
        None,
        True,
        None,
    ]
    assert enriched[2]["jd_text"] == ""
    assert enriched[3]["jd_text"] == "x" * 200


def test_pipeline_scores_fetched_jd_and_records_fetch_health(tmp_path: Path) -> None:
    harvest = load_harvest_module()
    search_fixture = FIXTURE_PATH.read_text(encoding="utf-8")
    full_jd = (
        "Requirements: Proven experience with C# .NET is mandatory. "
        "Build backend services and maintain production systems. " * 4
    )

    def jd_fetcher(_url: str) -> dict[str, object]:
        return {
            "jd_text": full_jd,
            "jd_chars": len(full_jd),
            "fetch_method": "guest-html",
            "fetch_error": None,
        }

    result = harvest.run_pipeline(
        config_path=SEARCHES_PATH,
        profile_path=PROFILE_PATH,
        output_dir=tmp_path,
        date_string="2026-08-12",
        harvested_at="2026-08-12T13:00:00Z",
        max_pages=1,
        fetcher=lambda _url: search_fixture,
        before_request=lambda: None,
        jd_fetcher=jd_fetcher,
        jd_sleep=lambda _seconds: None,
        jd_fetch_cap=40,
    )

    rows = [
        json.loads(line)
        for line in (tmp_path / "2026-08-12.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert result["jd_fetch_attempted"] == 2
    assert result["jd_fetch_failed"] == 0
    assert result["jd_fetch_degraded"] is False
    assert all(row["jd_fetched"] is True for row in rows)
    assert all(row["fetch_method"] == "guest-html" for row in rows)
    assert all({"c#", ".net"} <= set(row["negative_hits"]) for row in rows)


def test_jd_fetch_cap_argument_defaults_to_40_and_rejects_negative_values() -> None:
    harvest = load_harvest_module()
    parser = harvest.build_argument_parser()

    assert parser.parse_args([]).jd_fetch_cap == 40
    with pytest.raises(SystemExit, match="--jd-fetch-cap must be non-negative"):
        harvest.main(["--jd-fetch-cap", "-1"])


def test_pipeline_zero_jd_fetch_cap_skips_without_crashing(tmp_path: Path) -> None:
    harvest = load_harvest_module()
    search_fixture = FIXTURE_PATH.read_text(encoding="utf-8")

    result = harvest.run_pipeline(
        config_path=SEARCHES_PATH,
        profile_path=PROFILE_PATH,
        output_dir=tmp_path,
        date_string="2026-08-12",
        harvested_at="2026-08-12T13:00:00Z",
        max_pages=1,
        fetcher=lambda _url: search_fixture,
        before_request=lambda: None,
        jd_fetcher=lambda _url: pytest.fail("fetch called with a zero cap"),
        jd_sleep=lambda _seconds: pytest.fail("sleep called with a zero cap"),
        jd_fetch_cap=0,
    )

    rows = [
        json.loads(line)
        for line in (tmp_path / "2026-08-12.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert result["jd_fetch_attempted"] == 0
    assert result["jd_fetch_failed"] == 0
    assert result["jd_fetched_count"] == 0
    assert all(row["jd_fetched"] is False for row in rows)


def test_pipeline_rejects_negative_jd_fetch_cap_before_work(tmp_path: Path) -> None:
    harvest = load_harvest_module()

    with pytest.raises(ValueError, match="jd_fetch_cap must be non-negative"):
        harvest.run_pipeline(
            config_path=tmp_path / "missing-searches.json",
            profile_path=tmp_path / "missing-profile.md",
            output_dir=tmp_path,
            date_string="2026-08-12",
            harvested_at="2026-08-12T13:00:00Z",
            max_pages=1,
            fetcher=lambda _url: pytest.fail("work started for an invalid cap"),
            before_request=lambda: pytest.fail("work started for an invalid cap"),
            jd_fetch_cap=-1,
        )


def test_jd_fetch_degraded_requires_strictly_more_than_half_failures() -> None:
    harvest = load_harvest_module()

    assert harvest.jd_fetch_is_degraded(attempted=3, failed=2) is True
    assert harvest.jd_fetch_is_degraded(attempted=2, failed=1) is False
    assert harvest.jd_fetch_is_degraded(attempted=0, failed=0) is False


def test_pipeline_marks_more_than_half_failed_jd_fetches_degraded(tmp_path: Path) -> None:
    harvest = load_harvest_module()
    search_fixture = FIXTURE_PATH.read_text(encoding="utf-8")

    result = harvest.run_pipeline(
        config_path=SEARCHES_PATH,
        profile_path=PROFILE_PATH,
        output_dir=tmp_path,
        date_string="2026-08-12",
        harvested_at="2026-08-12T13:00:00Z",
        max_pages=1,
        fetcher=lambda _url: search_fixture,
        before_request=lambda: None,
        jd_fetcher=lambda _url: {
            "jd_text": "",
            "jd_chars": 0,
            "fetch_method": "failed",
            "fetch_error": "blocked",
        },
        jd_sleep=lambda _seconds: None,
    )

    assert result["jd_fetch_attempted"] == 2
    assert result["jd_fetch_failed"] == 2
    assert result["jd_fetch_degraded"] is True
    assert result["warning_count"] == 2


def test_summary_renders_prominent_jd_fetch_degraded_warning(
    tmp_path: Path,
) -> None:
    harvest = load_harvest_module()

    harvest.write_summary(
        tmp_path / "feed",
        "2026-08-12",
        [],
        harvested_count=3,
        skipped_seen=0,
        warning_count=2,
        jd_fetch_degraded=True,
    )
    summary = (tmp_path / "feed" / "latest-summary.md").read_text(encoding="utf-8")
    warning = harvest.JD_FETCH_DEGRADED_WARNING
    assert f"> [!WARNING]\n> {warning}" in summary
    assert "—" not in warning


def test_dedupe_uses_every_prior_day_and_removes_in_run_duplicates(tmp_path: Path) -> None:
    harvest = load_harvest_module()
    (tmp_path / "2026-08-07.jsonl").write_text('{"id":"old-1"}\n', encoding="utf-8")
    (tmp_path / "2026-08-08.jsonl").write_text(
        '{"id":"old-2"}\nnot-json\n', encoding="utf-8"
    )
    (tmp_path / "2026-08-09.jsonl").write_text('{"id":"today"}\n', encoding="utf-8")

    seen = harvest.load_prior_ids(tmp_path, current_date="2026-08-09")
    fresh = harvest.dedupe_postings(
        [
            {"id": "old-1"},
            {"id": "old-2"},
            {"id": "new-1"},
            {"id": "new-1"},
        ],
        seen,
    )

    assert seen == {"old-1", "old-2"}
    assert fresh == [{"id": "new-1"}]


def test_load_prior_ids_excludes_current_and_future_dated_files(tmp_path: Path) -> None:
    harvest = load_harvest_module()
    (tmp_path / "2026-08-08.jsonl").write_text('{"id":"past"}\n', encoding="utf-8")
    (tmp_path / "2026-08-09.jsonl").write_text('{"id":"today"}\n', encoding="utf-8")
    (tmp_path / "2026-08-10.jsonl").write_text('{"id":"future"}\n', encoding="utf-8")

    assert harvest.load_prior_ids(tmp_path, current_date="2026-08-09") == {"past"}


def test_load_searches_has_transitional_regional_examples() -> None:
    harvest = load_harvest_module()
    searches = harvest.load_searches(SEARCHES_PATH)

    assert [search["keywords"] for search in searches] == [
        "Software Engineer",
        "Full Stack Engineer",
        "Frontend Engineer",
        "Backend Engineer",
        "Product Engineer",
        "Platform Engineer",
        "AI Engineer",
        "Machine Learning Engineer",
        "Site Reliability Engineer",
        "Engineering Manager",
    ]
    assert {search["location"] for search in searches} == {"Israel"}
    assert {search["recency"] for search in searches} == {"r10800"}


@pytest.mark.parametrize("recency", ["r10800", "r43200", "r604800", "r2592000"])
def test_recency_override_applies_to_every_search(recency: str) -> None:
    harvest = load_harvest_module()
    searches = harvest.load_searches(SEARCHES_PATH)

    overridden = harvest.apply_recency_override(searches, recency)

    assert {search["recency"] for search in overridden} == {recency}
    assert [search["keywords"] for search in overridden] == [
        search["keywords"] for search in searches
    ]
    assert {search["recency"] for search in searches} == {"r10800"}




def test_profile_contract_is_read_without_yaml_dependency() -> None:
    harvest = load_harvest_module()
    profile = harvest.load_profile_contract(PROFILE_PATH)

    assert profile["contract_version"] == 1
    assert "full-stack" in profile["positioning"]
    assert {"frontend", "fullstack", "agents"} <= profile["fit_terms"]
    prohibited_block = PROFILE_PATH.read_text(encoding="utf-8").split(
        "prohibited:\n", 1
    )[1].split("safe_radar_projection:\n", 1)[0]
    expected_prohibited = sum(
        line.startswith("- ") for line in prohibited_block.splitlines()
    )
    assert profile["prohibited_count"] == expected_prohibited


def test_profile_contract_reads_fit_terms_without_shipment_artifacts(
    tmp_path: Path,
) -> None:
    harvest = load_harvest_module()
    profile_path = tmp_path / "profile-export.yaml"
    profile_path.write_text(
        """contract_version: 1
profile:
  positioning: Full-stack engineer
  tenure_years: 3.7
  location: Israel
  fit_terms:
  - frontend
  - fullstack
  - agents
artifacts: []
connectors: []
prohibited:
- Kubernetes
""",
        encoding="utf-8",
    )

    profile = harvest.load_profile_contract(profile_path)

    assert profile["fit_terms"] == {"frontend", "fullstack", "agents"}


def test_build_search_url_uses_live_guest_endpoint_and_recency() -> None:
    harvest = load_harvest_module()
    url = harvest.build_search_url(
        {"keywords": "AI Engineer", "location": "Israel", "recency": "r10800"},
        start=25,
    )

    assert "/jobs-guest/jobs/api/seeMoreJobPostings/search?" in url
    assert "keywords=AI+Engineer" in url
    assert "location=Israel" in url
    assert "f_TPR=r10800" in url
    assert "start=25" in url


class FakeResponse:
    def __init__(self, body: bytes) -> None:
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def read(self) -> bytes:
        return self.body


def test_fetch_html_retries_with_backoff_then_succeeds() -> None:
    harvest = load_harvest_module()
    attempts: list[int] = []
    sleeps: list[float] = []

    def flaky_opener(_request, timeout):
        attempts.append(timeout)
        if len(attempts) < 3:
            raise URLError("temporary block")
        return FakeResponse(b"<li>ok</li>")

    html = harvest.fetch_html(
        "https://example.test/jobs",
        opener=flaky_opener,
        sleep=sleeps.append,
        backoffs=(1.0, 2.0),
    )

    assert html == "<li>ok</li>"
    assert len(attempts) == 3
    assert sleeps == [1.0, 2.0]


def test_fetch_html_returns_none_after_retry_budget() -> None:
    harvest = load_harvest_module()
    sleeps: list[float] = []

    def blocked_opener(_request, timeout):
        raise URLError("blocked")

    assert harvest.fetch_html(
        "https://example.test/jobs",
        opener=blocked_opener,
        sleep=sleeps.append,
        backoffs=(1.0, 2.0),
    ) is None
    assert sleeps == [1.0, 2.0]


def test_append_jsonl_schema_and_latest_summary(tmp_path: Path) -> None:
    harvest = load_harvest_module()
    posting = {
        "id": "new-1",
        "title": "Full Stack AI Engineer",
        "company": "Example Co",
        "location": "Tel Aviv, Israel",
        "url": "https://www.linkedin.com/jobs/view/example-1",
        "posted_ago": "22 minutes ago",
        "updated_at": "2026-08-09T09:15:00Z",
        "harvested_at": "2026-08-09T09:30:00Z",
        "score": 9,
        "score_title": 6,
        "jd_fetched": True,
        "senior_titled": False,
        "matched_keywords": ["full-stack", "ai"],
        "negative_hits": ["react-native"],
        "raw_text": "must never leak into output",
    }

    output_path = harvest.append_postings(tmp_path, "2026-08-09", [posting])
    harvest.write_summary(
        tmp_path,
        "2026-08-09",
        [posting],
        harvested_count=4,
        skipped_seen=3,
        warning_count=0,
    )

    row = json.loads(output_path.read_text(encoding="utf-8"))
    assert set(row) == {
        "id", "title", "company", "location", "url", "posted_ago", "updated_at",
        "harvested_at", "score", "score_title", "jd_fetched",
        "jd_chars", "fetch_method",
        "senior_titled", "matched_keywords", "negative_hits",
            "core_stack_present", "ai_bonus_gated", "employer_class",
            "employer_class_note", "source", "source_tenant", "alive",
            "liveness_status", "liveness_reason", "liveness_final_url",
            "liveness_checked_at",
        }
    summary = (tmp_path / "latest-summary.md").read_text(encoding="utf-8")
    assert "Harvested cards: 4" in summary
    assert "New postings: 1" in summary
    assert "Previously seen: 3" in summary
    assert "Full Stack AI Engineer" in summary
    assert "JD fetched: 1/1" in summary
    assert "| JD |" in summary
    assert "react-native" in summary
    assert "Updated 2026-08-09T09:15:00Z" in summary
    assert row["updated_at"] == "2026-08-09T09:15:00Z"
    assert row["employer_class"] == "unknown"
    assert row["jd_chars"] == 0
    assert row["fetch_method"] == ""
    assert row["employer_class_note"] == ""


def test_append_jsonl_defaults_new_enrichment_fields(tmp_path: Path) -> None:
    harvest = load_harvest_module()
    posting = {
        "id": "fallback-1",
        "title": "Software Engineer",
        "company": "Example Co",
        "location": "Israel",
        "url": "https://www.linkedin.com/jobs/view/fallback-1",
        "posted_ago": "1 hour ago",
        "harvested_at": "2026-08-09T09:30:00Z",
        "score": 0,
        "senior_titled": False,
        "matched_keywords": [],
    }

    output_path = harvest.append_postings(tmp_path, "2026-08-09", [posting])
    harvest.write_summary(
        tmp_path,
        "2026-08-09",
        [posting],
        harvested_count=1,
        skipped_seen=0,
        warning_count=0,
    )

    row = json.loads(output_path.read_text(encoding="utf-8"))
    assert row["score_title"] == 0
    assert row["jd_fetched"] is False
    assert row["negative_hits"] == []
    assert row["core_stack_present"] is False
    assert row["ai_bonus_gated"] is False
    assert row["employer_class"] == "unknown"
    assert row["employer_class_note"] == ""
    assert row["updated_at"] == ""
    summary = (tmp_path / "latest-summary.md").read_text(encoding="utf-8")
    assert "| Score | Title score | JD |" in summary
    assert "| 0 | 0 | title-only |" in summary


def test_summary_shows_employer_marker_and_fit_line_under_role(tmp_path: Path) -> None:
    harvest = load_harvest_module()
    posting = {
        "id": "agency-1",
        "title": "Backend Engineer",
        "company": "Gotfriends",
        "location": "Tel Aviv, Israel",
        "url": "https://www.linkedin.com/jobs/view/agency-1",
        "posted_ago": "1 hour ago",
        "harvested_at": "2026-08-10T06:30:00Z",
        "score": 6,
        "score_title": 0,
        "jd_fetched": True,
        "senior_titled": False,
        "matched_keywords": ["node"],
        "negative_hits": [],
        "core_stack_present": True,
        "ai_bonus_gated": False,
        "employer_type": "agency",
        "seniority_real": None,
        "fit_line": "Node.js overlap, but the client and product are undisclosed.",
        "luna_status": "ok",
    }

    harvest.write_summary(
        tmp_path,
        "2026-08-10",
        [posting],
        harvested_count=1,
        skipped_seen=0,
        warning_count=0,
    )

    summary = (tmp_path / "latest-summary.md").read_text(encoding="utf-8")
    assert "| Employer |" in summary
    assert "🏢 Agency" in summary
    assert ")<br><sub>Node.js overlap" in summary


@pytest.mark.parametrize(
    ("posting", "expected_class"),
    [
        ({"company": "GotFriends", "source": "linkedin"}, "staffing"),
        ({"company": "Medulla", "source": "linkedin"}, "staffing"),
        ({"company": "Ethosia", "source": "linkedin"}, "staffing"),
        ({"company": "Talent-HR", "source": "linkedin"}, "staffing"),
        ({"company": "Mertens", "source": "linkedin"}, "staffing"),
        (
            {
                "company": "Mertens",
                "source": "linkedin",
                "jd_text": "Confidential search for a specialist engineering leader",
            },
            "headhunter",
        ),
        (
            {
                "company": "Recruiter Co",
                "source": "linkedin",
                "jd_text": "אנחנו מגייסים עבור לקוח שלנו בתל אביב",
            },
            "staffing",
        ),
        ({"company": "Acme", "source": "greenhouse"}, "direct"),
        ({"company": "Acme", "source": "linkedin"}, "unknown"),
    ],
)
def test_employer_classification_is_deterministic_and_keeps_agency_types_distinct(
    posting: dict[str, object], expected_class: str
) -> None:
    harvest = load_harvest_module()

    classified = harvest.classify_employer(posting)

    assert classified["employer_class"] == expected_class
    if expected_class == "headhunter":
        assert "5-6yr gate" in classified["employer_class_note"]


def test_employer_classification_is_additive_and_does_not_filter_or_rescore() -> None:
    harvest = load_harvest_module()
    posting = {
        "id": "headhunter-1",
        "company": "Search Partners",
        "source": "linkedin",
        "jd_text": "Discreet search for a senior engineer",
        "score": 7,
    }

    classified = harvest.apply_employer_classification([posting])

    assert len(classified) == 1
    assert classified[0]["id"] == "headhunter-1"
    assert classified[0]["score"] == 7
    assert classified[0]["employer_class"] == "headhunter"




@pytest.mark.parametrize("employer_type", ["direct", "agency", "unknown", None])
def test_employer_classification_is_invariant_to_luna_employer_type(
    employer_type: str | None,
) -> None:
    harvest = load_harvest_module()
    posting = {
        "company": "Acme",
        "source": "linkedin",
    }
    if employer_type is not None:
        posting["employer_type"] = employer_type

    assert harvest.classify_employer(posting) == {
        "employer_class": "unknown",
        "employer_class_note": "",
    }


def test_summary_includes_headhunter_gate_note_in_role_fit_line(tmp_path: Path) -> None:
    harvest = load_harvest_module()
    posting = {
        "id": "headhunter-summary",
        "title": "Backend Engineer",
        "company": "Search Partners",
        "location": "Tel Aviv, Israel",
        "url": "https://example.test/headhunter-summary",
        "posted_ago": "1 hour ago",
        "score": 7,
        "score_title": 4,
        "jd_fetched": True,
        "senior_titled": False,
        "matched_keywords": ["node"],
        "negative_hits": [],
        "core_stack_present": True,
        "ai_bonus_gated": False,
        "employer_class": "headhunter",
        "employer_class_note": "Headhunter signal; 5-6yr gate; flagged, never filtered.",
        "employer_type": "agency",
        "fit_line": "Strong Node.js overlap.",
        "luna_status": "ok",
    }

    harvest.write_summary(
        tmp_path,
        "2026-08-11",
        [posting],
        harvested_count=1,
        skipped_seen=0,
        warning_count=0,
    )

    summary = (tmp_path / "latest-summary.md").read_text(encoding="utf-8")
    assert "5-6yr gate" in summary
    assert "flagged, never filtered" in summary


@pytest.mark.parametrize(
    "company",
    [
        "GotFriends Ltd",
        "Ethosia Human Resources",
        "Medulla Recruitment",
        "Mertens Group",
        "Talent-HR Israel",
    ],
)
def test_staffing_seed_matches_normalized_company_name_variants(company: str) -> None:
    harvest = load_harvest_module()

    classified = harvest.classify_employer(
        {"company": company, "source": "linkedin"}
    )

    assert classified["employer_class"] == "staffing"


def test_write_summary_atomically_replaces_complete_temporary_file(
    tmp_path: Path, monkeypatch
) -> None:
    harvest = load_harvest_module()
    replace_calls: list[tuple[Path, Path]] = []
    original_replace = Path.replace

    def observing_replace(source: Path, target: Path):
        replace_calls.append((source, target))
        text = source.read_text(encoding="utf-8")
        assert text.startswith("# Job feed — 2026-08-10")
        assert "- New postings: 0" in text
        assert text.endswith("\n")
        return original_replace(source, target)

    monkeypatch.setattr(Path, "replace", observing_replace)
    result = harvest.write_summary(
        tmp_path,
        "2026-08-10",
        [],
        harvested_count=0,
        skipped_seen=0,
        warning_count=0,
    )

    assert replace_calls == [
        (tmp_path / "latest-summary.md.tmp", tmp_path / "latest-summary.md")
    ]
    assert result == tmp_path / "latest-summary.md"
    assert not (tmp_path / "latest-summary.md.tmp").exists()


















def test_load_triage_verdicts_is_optional_and_invalid_files_fail_safe(
    tmp_path: Path, caplog
) -> None:
    harvest = load_harvest_module()

    assert harvest.load_triage_verdicts(tmp_path / "missing.json") == {}

    invalid = tmp_path / "verdicts-2026-08-11.json"
    invalid.write_text('{"Example": {"verdict": "LUNA", "reason": "no"}}', encoding="utf-8")
    assert harvest.load_triage_verdicts(invalid) == {}
    assert "Skipping invalid triage verdict entry 'Example'" in caplog.text


def test_load_triage_verdicts_keeps_valid_entries_when_one_entry_is_malformed(
    tmp_path: Path, caplog
) -> None:
    harvest = load_harvest_module()
    path = tmp_path / "verdicts-2026-08-11.json"
    path.write_text(
        json.dumps(
            {
                "Good": {"verdict": "APPLY", "reason": "Exact fit"},
                "Extra": {"verdict": "SKIP", "reason": "No", "note": "manual"},
                "id:4440182633": {"verdict": "REFERRAL", "reason": "Warm path"},
            }
        ),
        encoding="utf-8",
    )

    assert harvest.load_triage_verdicts(path) == {
        "good": {"verdict": "APPLY", "reason": "Exact fit"},
        "id:4440182633": {"verdict": "REFERRAL", "reason": "Warm path"},
    }
    assert "Extra" in caplog.text
























def test_pipeline_annotates_only_positive_scores_and_persists_additive_fields(
    tmp_path: Path, monkeypatch
) -> None:
    harvest = load_harvest_module()
    fixture = FIXTURE_PATH.read_text(encoding="utf-8")
    jd_fixture = JD_FIXTURE_PATH.read_text(encoding="utf-8")
    original_score = harvest.score_posting
    calls: list[str] = []

    def score_with_non_positive_boundaries(posting, profile_fit_terms=None):
        scored = original_score(posting, profile_fit_terms)
        scored["score"] = 4 if posting["id"] == "4449293792" else 0
        return scored

    def annotator(posting):
        calls.append(str(posting["id"]))
        return {
            "employer_type": "agency",
            "seniority_real": None,
            "fit_line": "Relevant stack, but the end employer is undisclosed.",
            "luna_status": "ok",
        }

    def fetcher(url: str) -> str:
        return jd_fixture if "/jobPosting/" in url else fixture

    monkeypatch.setattr(harvest, "score_posting", score_with_non_positive_boundaries)
    ticks = iter((10.0, 10.0, 12.5))
    result = harvest.run_pipeline(
        config_path=SEARCHES_PATH,
        profile_path=PROFILE_PATH,
        output_dir=tmp_path,
        date_string="2026-08-10",
        harvested_at="2026-08-10T06:30:00Z",
        max_pages=1,
        fetcher=fetcher,
        before_request=lambda: None,
        annotator=annotator,
        # Exhausting the controlled clock must fail the test loudly.
        clock=lambda: next(ticks),  # skipcq: PTC-W0063
    )

    rows = [
        json.loads(line)
        for line in (tmp_path / "2026-08-10.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    by_id = {row["id"]: row for row in rows}
    assert calls == ["4449293792"]
    assert by_id["4449293792"]["employer_type"] == "agency"
    assert by_id["4449293792"]["luna_status"] == "ok"
    assert "luna_status" not in by_id["4449288878"]
    assert by_id["4449293792"]["score"] == 4
    assert by_id["4449288878"]["score"] == 0
    assert result["annotation_count"] == 1
    assert result["annotation_unavailable_count"] == 0
    assert result["annotation_seconds"] == 2.5


def test_pipeline_writes_complete_base_artifacts_before_first_annotation(
    tmp_path: Path, monkeypatch
) -> None:
    harvest = load_harvest_module()
    fixture = FIXTURE_PATH.read_text(encoding="utf-8")
    jd_fixture = JD_FIXTURE_PATH.read_text(encoding="utf-8")
    original_score = harvest.score_posting
    observed = False
    events: list[str] = []

    def fetcher(url: str) -> str:
        return jd_fixture if "/jobPosting/" in url else fixture

    def positive_score(posting, profile_fit_terms=None):
        scored = original_score(posting, profile_fit_terms)
        scored["score"] = 4
        return scored

    def inspecting_annotator(_posting):
        nonlocal observed
        events.append("annotate")
        if not observed:
            rows = [
                json.loads(line)
                for line in (tmp_path / "job-feed" / "2026-08-10.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
            ]
            summary = (tmp_path / "job-feed" / "latest-summary.md").read_text(encoding="utf-8")
            assert {row["id"] for row in rows} == {"4449293792", "4449288878"}
            assert all("luna_status" not in row for row in rows)
            assert "- New postings: 2" in summary
            assert "Full Stack Engineer" in summary
            assert "Full Stack Next.js Developer" in summary
            observed = True
        return {
            "employer_type": "direct",
            "seniority_real": True,
            "fit_line": "Strong stack overlap.",
            "luna_status": "ok",
        }

    monkeypatch.setattr(harvest, "score_posting", positive_score)
    harvest.run_pipeline(
        config_path=SEARCHES_PATH,
        profile_path=PROFILE_PATH,
        output_dir=tmp_path / "job-feed",
        date_string="2026-08-10",
        harvested_at="2026-08-10T06:30:00Z",
        max_pages=1,
        fetcher=fetcher,
        before_request=lambda: None,
        annotator=inspecting_annotator,
    )

    assert observed is True
    assert events[0] == "annotate"






def test_annotation_budget_skips_remaining_positive_rows_without_calls() -> None:
    harvest = load_harvest_module()
    calls: list[str] = []
    ticks = iter((0.0, 6.0))

    def annotator(posting):
        calls.append(str(posting["id"]))
        return {
            "employer_type": "direct",
            "seniority_real": True,
            "fit_line": "Strong fit.",
            "luna_status": "ok",
        }

    rows, attempted, unavailable, invalid = harvest.annotate_positive_postings(
        [{"id": "first", "score": 1}, {"id": "second", "score": 2}],
        annotator,
        deadline=5.0,
        # Exhausting the controlled clock must fail the test loudly.
        clock=lambda: next(ticks),  # skipcq: PTC-W0063
    )

    assert calls == ["first"]
    assert attempted == 1
    assert unavailable == 1
    assert invalid == 0
    assert rows[0]["luna_status"] == "ok"
    assert rows[1]["luna_status"] == "unavailable"


def test_pipeline_counts_invalid_annotations(tmp_path: Path, monkeypatch) -> None:
    harvest = load_harvest_module()
    fixture = FIXTURE_PATH.read_text(encoding="utf-8")
    jd_fixture = JD_FIXTURE_PATH.read_text(encoding="utf-8")
    original_score = harvest.score_posting

    def fetcher(url: str) -> str:
        return jd_fixture if "/jobPosting/" in url else fixture

    def positive_score(posting, profile_fit_terms=None):
        scored = original_score(posting, profile_fit_terms)
        scored["score"] = 4
        return scored

    monkeypatch.setattr(harvest, "score_posting", positive_score)
    result = harvest.run_pipeline(
        config_path=SEARCHES_PATH,
        profile_path=PROFILE_PATH,
        output_dir=tmp_path,
        date_string="2026-08-10",
        harvested_at="2026-08-10T06:30:00Z",
        max_pages=1,
        fetcher=fetcher,
        before_request=lambda: None,
        annotator=lambda _posting: dict(harvest.LUNA_INVALID),
    )

    assert result["annotation_count"] == 2
    assert result["annotation_unavailable_count"] == 0
    assert result["annotation_invalid_count"] == 2


def test_pipeline_annotator_exception_mid_run_leaves_complete_feed_on_disk(
    tmp_path: Path, monkeypatch
) -> None:
    harvest = load_harvest_module()
    fixture = FIXTURE_PATH.read_text(encoding="utf-8")
    jd_fixture = JD_FIXTURE_PATH.read_text(encoding="utf-8")
    calls = 0
    original_score = harvest.score_posting

    def fetcher(url: str) -> str:
        return jd_fixture if "/jobPosting/" in url else fixture

    def positive_score(posting, profile_fit_terms=None):
        scored = original_score(posting, profile_fit_terms)
        scored["score"] = 4
        return scored

    def crashing_annotator(_posting):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("simulated annotator death")
        return {
            "employer_type": "direct",
            "seniority_real": False,
            "fit_line": "Good stack overlap; the title's seniority is inflated.",
            "luna_status": "ok",
        }

    monkeypatch.setattr(harvest, "score_posting", positive_score)
    result = harvest.run_pipeline(
        config_path=SEARCHES_PATH,
        profile_path=PROFILE_PATH,
        output_dir=tmp_path,
        date_string="2026-08-10",
        harvested_at="2026-08-10T06:30:00Z",
        max_pages=1,
        fetcher=fetcher,
        before_request=lambda: None,
        annotator=crashing_annotator,
    )

    path = tmp_path / "2026-08-10.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 2
    assert {row["id"] for row in rows} == {"4449293792", "4449288878"}
    assert all("score" in row and "title" in row for row in rows)
    assert rows[0]["luna_status"] == "ok"
    assert rows[1]["luna_status"] == "unavailable"
    assert result["new_count"] == 2
    assert result["annotation_count"] == 2
    assert result["annotation_unavailable_count"] == 1


def test_sigkill_mid_annotation_leaves_complete_base_feed_and_summary(
    tmp_path: Path,
) -> None:
    sentinel = tmp_path / "annotator-started"
    child_code = f"""
import importlib.util
import time
from pathlib import Path

spec = importlib.util.spec_from_file_location("job_feed_harvest_child", {str(HARVEST_PATH)!r})
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
fixture = Path({str(FIXTURE_PATH)!r}).read_text(encoding="utf-8")
jd_fixture = Path({str(JD_FIXTURE_PATH)!r}).read_text(encoding="utf-8")
original_score = module.score_posting

def fetcher(url):
    return jd_fixture if "/jobPosting/" in url else fixture

def positive_score(posting, profile_fit_terms=None):
    scored = original_score(posting, profile_fit_terms)
    scored["score"] = 4
    return scored

def sleeping_annotator(_posting):
    Path({str(sentinel)!r}).touch()
    time.sleep(60)

module.score_posting = positive_score
module.run_pipeline(
    config_path=Path({str(SEARCHES_PATH)!r}),
    profile_path=Path({str(PROFILE_PATH)!r}),
    output_dir=Path({str(tmp_path)!r}),
    date_string="2026-08-10",
    harvested_at="2026-08-10T06:30:00Z",
    max_pages=1,
    fetcher=fetcher,
    before_request=lambda: None,
    annotator=sleeping_annotator,
)
"""
    child = subprocess.Popen([sys.executable, "-c", child_code])
    deadline = time.monotonic() + 5
    try:
        while not sentinel.exists() and child.poll() is None and time.monotonic() < deadline:
            time.sleep(0.01)
        assert sentinel.exists(), "child never entered the sleeping annotator"
        os.kill(child.pid, signal.SIGKILL)
        assert child.wait(timeout=5) == -signal.SIGKILL
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=5)

    rows = [
        json.loads(line)
        for line in (tmp_path / "2026-08-10.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    summary = (tmp_path / "latest-summary.md").read_text(encoding="utf-8")
    assert {row["id"] for row in rows} == {"4449293792", "4449288878"}
    assert all("score" in row and "title" in row for row in rows)
    assert "- New postings: 2" in summary
    assert "Full Stack Engineer" in summary
    assert "Full Stack Next.js Developer" in summary


def test_profile_fit_terms_add_a_small_transparent_signal() -> None:
    harvest = load_harvest_module()
    scored = harvest.score_posting(
        {"title": "Frontend Engineer", "raw_text": "Frontend Engineer"},
        profile_fit_terms={"frontend", "fullstack", "agents"},
    )

    assert scored["score"] == 1
    assert scored["matched_keywords"] == ["frontend"]


@pytest.mark.parametrize(
    ("title", "requirement", "expected_hit"),
    [
        (
            "Full Stack Developer",
            "Strong proficiency experience in Python. Strong familiarity with Infrastructure as Code (e.g., Terraform) and containerization (Docker, Kubernetes).",
            {"python-primary", "infra:terraform", "infra:docker", "infra:kubernetes"},
        ),
        (
            "Full Stack Engineer",
            "5+ years of professional experience as a Software Developer, with a focus on Python development. Experience using Docker and Kubernetes.",
            {"python-primary", "infra:docker", "infra:kubernetes"},
        ),
        (
            "Senior Backend Engineer",
            "Language Proficiency: Deep proficiency in **Python** (or equivalent backend languages).",
            {"python-primary"},
        ),
    ],
)
def test_required_infra_and_python_primary_are_strong_negative_walls(
    title: str, requirement: str, expected_hit: set[str]
) -> None:
    harvest = load_harvest_module()

    scored = harvest.score_posting(
        {
            "title": title,
            "raw_text": title,
            "jd_fetched": True,
            "jd_text": requirement,
        }
    )

    assert expected_hit <= set(scored["negative_hits"])
    assert scored["score"] <= 0


def test_python_or_list_is_not_treated_as_python_primary() -> None:
    harvest = load_harvest_module()

    scored = harvest.score_posting(
        {
            "title": "Full Stack Engineer",
            "raw_text": "Full Stack Engineer React Node.js AI",
            "jd_fetched": True,
            "jd_text": "Experience with Python, TypeScript, or similar languages.",
        }
    )

    assert "python-primary" not in scored["negative_hits"]
    assert scored["score"] > 0


def test_python_primary_is_found_after_an_earlier_non_requirement_mention() -> None:
    harvest = load_harvest_module()

    scored = harvest.score_posting(
        {
            "title": "Backend Engineer",
            "raw_text": "Backend Engineer",
            "jd_fetched": True,
            "jd_text": (
                "Our existing services include Python. "
                "Requirements: Deep proficiency in Python for backend development."
            ),
        }
    )

    assert "python-primary" in scored["negative_hits"]
    assert scored["score"] <= 0


def test_infra_mentions_without_requirement_language_are_not_penalized() -> None:
    harvest = load_harvest_module()

    scored = harvest.score_posting(
        {
            "title": "Full Stack Engineer",
            "raw_text": "Full Stack Engineer React Node.js",
            "jd_fetched": True,
            "jd_text": "Our platform currently runs on Docker, Kubernetes, and Terraform.",
        }
    )

    assert not any(hit.startswith("infra:") for hit in scored["negative_hits"])
    assert scored["score"] > 0


def test_harvest_search_paginates_and_stops_on_empty_page() -> None:
    harvest = load_harvest_module()
    fixture = FIXTURE_PATH.read_text(encoding="utf-8")
    starts: list[int] = []
    paced: list[bool] = []

    def fetcher(url: str) -> str:
        start = int(parse_qs(urlparse(url).query)["start"][0])
        starts.append(start)
        return fixture if start == 0 else ""

    postings, warnings = harvest.harvest_search(
        {"keywords": "Full Stack Engineer", "location": "Israel", "recency": "r10800"},
        max_pages=3,
        page_size=2,
        fetcher=fetcher,
        before_request=lambda: paced.append(True),
    )

    assert [posting["id"] for posting in postings] == ["4449293792", "4449288878"]
    assert starts == [0, 2]
    assert paced == [True, True]
    assert warnings == 0


def test_harvest_search_degrades_on_first_page_block() -> None:
    harvest = load_harvest_module()
    postings, warnings = harvest.harvest_search(
        {"keywords": "AI Engineer", "location": "Israel", "recency": "r10800"},
        max_pages=3,
        fetcher=lambda _url: None,
        before_request=lambda: None,
    )

    assert postings == []
    assert warnings == 1


def test_run_pipeline_dedupes_prior_and_current_files(tmp_path: Path) -> None:
    harvest = load_harvest_module()
    fixture = FIXTURE_PATH.read_text(encoding="utf-8")
    jd_fixture = JD_FIXTURE_PATH.read_text(encoding="utf-8")
    (tmp_path / "2026-08-08.jsonl").write_text(
        '{"id":"4449293792"}\n', encoding="utf-8"
    )
    (tmp_path / "2026-08-09.jsonl").write_text(
        '{"id":"already-today"}\n', encoding="utf-8"
    )

    def fetcher(url: str) -> str:
        return jd_fixture if "/jobPosting/" in url else fixture

    result = harvest.run_pipeline(
        config_path=SEARCHES_PATH,
        profile_path=PROFILE_PATH,
        output_dir=tmp_path,
        date_string="2026-08-09",
        harvested_at="2026-08-09T09:30:00Z",
        max_pages=1,
        fetcher=fetcher,
        before_request=lambda: None,
    )

    rows = [
        json.loads(line)
        for line in (tmp_path / "2026-08-09.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert result == {
        "harvested_count": 20,
        "new_count": 1,
        "new_published_count": 1,
        "jd_fetched_count": 1,
        "jd_fetch_attempted": 1,
        "jd_fetch_failed": 0,
        "jd_fetch_degraded": False,
        "skipped_seen": 1,
        "warning_count": 0,
        "annotation_count": 0,
        "annotation_unavailable_count": 0,
        "annotation_invalid_count": 0,
        "annotation_seconds": 0.0,
    }
    assert [row["id"] for row in rows] == ["already-today", "4449288878"]
    assert rows[-1]["jd_fetched"] is True


def test_overlapping_recency_windows_do_not_reemit_seen_postings(tmp_path: Path) -> None:
    harvest = load_harvest_module()
    fixture = FIXTURE_PATH.read_text(encoding="utf-8")
    jd_fixture = JD_FIXTURE_PATH.read_text(encoding="utf-8")

    def fetcher(url: str) -> str:
        return jd_fixture if "/jobPosting/" in url else fixture

    fresh_run = harvest.run_pipeline(
        config_path=SEARCHES_PATH,
        profile_path=PROFILE_PATH,
        output_dir=tmp_path,
        date_string="2026-08-10",
        harvested_at="2026-08-10T09:00:00Z",
        max_pages=1,
        fetcher=fetcher,
        before_request=lambda: None,
        recency_override="r10800",
    )
    overnight_run = harvest.run_pipeline(
        config_path=SEARCHES_PATH,
        profile_path=PROFILE_PATH,
        output_dir=tmp_path,
        date_string="2026-08-10",
        harvested_at="2026-08-10T03:30:00Z",
        max_pages=1,
        fetcher=fetcher,
        before_request=lambda: None,
        recency_override="r43200",
    )

    rows = [
        json.loads(line)
        for line in (tmp_path / "2026-08-10.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert fresh_run["new_count"] == 2
    assert overnight_run["new_count"] == 0
    assert overnight_run["skipped_seen"] == 2
    assert len(rows) == 2


def test_request_pacer_waits_two_to_four_seconds_after_first_request() -> None:
    harvest = load_harvest_module()
    sleeps: list[float] = []
    pacer = harvest.RequestPacer(
        sleep=sleeps.append,
        uniform=lambda low, high: (low + high) / 2,
    )

    pacer()
    pacer()
    pacer()

    assert sleeps == [3.0, 3.0]


def test_current_python_compiles_harvester(tmp_path: Path) -> None:
    env = os.environ.copy()
    env["PYTHONPYCACHEPREFIX"] = str(tmp_path)
    result = subprocess.run(
        [sys.executable, "-m", "py_compile", str(HARVEST_PATH)],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_main_rejects_traversal_style_date_before_network(monkeypatch) -> None:
    harvest = load_harvest_module()
    monkeypatch.setattr(
        harvest,
        "run_pipeline",
        lambda **_kwargs: pytest.fail("invalid date reached the pipeline"),
    )

    with pytest.raises(SystemExit, match="--date must use YYYY-MM-DD"):
        harvest.main(["--date", "../escape"])


def test_main_degrades_when_annotator_module_cannot_load(
    tmp_path: Path, monkeypatch
) -> None:
    harvest = load_harvest_module()
    captured: dict[str, object] = {}

    def broken_loader():
        raise SyntaxError("simulated broken annotator module")

    def fake_pipeline(**kwargs):
        captured.update(kwargs)
        return {"new_count": 0}

    monkeypatch.setattr(harvest, "load_luna_annotator", broken_loader)
    monkeypatch.setattr(harvest, "run_pipeline", fake_pipeline)

    result = harvest.main(
        [
            "--date",
            "2026-08-10",
            "--max-pages",
            "1",
            "--output-dir",
            str(tmp_path),
        ]
    )

    assert result == 0
    assert callable(captured["annotator"])
    assert captured["annotator"]({"id": "example"}) is None
    assert "dashboard_writer" not in captured
    assert "dashboard_publisher" not in captured


def test_append_postings_persists_explicit_source_provenance(tmp_path: Path) -> None:
    harvest = load_harvest_module()
    base = {
        "title": "Full Stack Engineer", "company": "Example", "location": "Israel",
        "url": "https://example.test/job", "posted_ago": "today",
        "harvested_at": "2026-08-26T12:00:00Z", "score": 1,
        "senior_titled": False, "matched_keywords": ["full-stack"],
    }
    path = harvest.append_postings(
        tmp_path, "2026-08-26",
        [
            {"id": "linkedin-1", **base},
            {"id": "lever:acme:1", **base, "source": "lever", "source_tenant": "acme"},
        ],
    )
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    assert [(row["source"], row["source_tenant"]) for row in rows] == [
        ("linkedin", "linkedin-guest"), ("lever", "acme")
    ]


def test_run_pipeline_persists_phase2_shape_ordered_by_fit_score(
    tmp_path: Path, monkeypatch
) -> None:
    harvest = load_harvest_module()
    fixture = FIXTURE_PATH.read_text(encoding="utf-8")
    original_score = harvest.score_posting

    def reversed_score(posting, profile_fit_terms=None):
        scored = original_score(posting, profile_fit_terms)
        scored["score"] = 99 if posting["id"] == "4449293792" else 1
        return scored

    monkeypatch.setattr(harvest, "score_posting", reversed_score)
    harvest.run_pipeline(
        config_path=SEARCHES_PATH, profile_path=PROFILE_PATH, output_dir=tmp_path,
        date_string="2026-08-26", harvested_at="2026-08-26T12:00:00Z",
        max_pages=1, fetcher=lambda _url: fixture, before_request=lambda: None,
        annotator=lambda posting: phase2_annotation(
            61 if posting["id"] == "4449293792" else 93
        ),
        jd_fetch_cap=0,
    )
    rows = [
        json.loads(line)
        for line in (tmp_path / "2026-08-26.jsonl").read_text().splitlines()
    ]
    assert [row["fit_score"] for row in rows] == [93, 61]
    assert all("fit_line_evidence_ids" in row and row["luna_status"] == "ok" for row in rows)


def test_run_pipeline_dispatches_registry_queries_and_isolates_tenants(
    tmp_path: Path, monkeypatch
) -> None:
    harvest = load_harvest_module()
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        harvest, "load_registry_source_queries",
        lambda: {
            "greenhouse": [{"board": "broken", "company": "Broken", "source_tenant": "broken"}],
            "lever": [{"account": "good", "company": "Good", "source_tenant": "good"}],
        },
    )
    monkeypatch.setattr(
        harvest, "harvest_search",
        lambda *_args, **_kwargs: ([{
            "id": "linkedin-1", "title": "Full Stack Engineer", "company": "LinkedIn Co",
            "location": "Israel", "url": "https://linkedin.test/1", "posted_ago": "today",
        }], 0),
    )

    def adapter_for(source):
        class Adapter:
            @staticmethod
            def fetch(query, **_kwargs):
                calls.append((source, query["source_tenant"]))
                if source == "greenhouse":
                    raise RuntimeError("broken tenant")
                return [{
                    "id": "lever:good:1", "title": "Full Stack Engineer",
                    "company": query["company"], "location": "Israel",
                    "url": "https://jobs.lever.co/good/1", "posted_ago": "today",
                    "jd_text": "Full stack TypeScript React Node product role. " * 6,
                    "jd_fetched": True,
                }]
        return Adapter

    monkeypatch.setattr(harvest, "load_source_adapter", adapter_for)
    result = harvest.run_pipeline(
        config_path=SEARCHES_PATH, profile_path=PROFILE_PATH, output_dir=tmp_path,
        date_string="2026-08-26", harvested_at="2026-08-26T12:00:00Z",
        max_pages=1, fetcher=lambda _url: "", before_request=lambda: None,
        enabled_sources={"greenhouse", "lever"}, jd_fetch_cap=0,
    )
    rows = [json.loads(line) for line in (tmp_path / "2026-08-26.jsonl").read_text().splitlines()]
    assert calls == [("greenhouse", "broken"), ("lever", "good")]
    assert result["source_counts"] == {"linkedin": 1, "greenhouse": 0, "lever": 1}
    assert result["source_fetch_counts"] == {"greenhouse": 0, "lever": 1}
    assert result["source_match_counts"] == {"linkedin": 0, "greenhouse": 0, "lever": 1}
    assert {(row["source"], row["source_tenant"]) for row in rows} == {
        ("linkedin", "linkedin-guest"), ("lever", "good")
    }
