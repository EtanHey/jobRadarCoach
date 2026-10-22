"""Role identity belongs to the advertised vacancy, never candidate fit evidence."""

from copy import deepcopy
from contextlib import nullcontext
import json

import pytest

from classifier import core, persistence
from scraper.test_annotate import structured_annotation


@pytest.mark.parametrize("title, expected", [
    ("Senior Full Stack Developer", "fullstack"),
    ("Front-end Engineer", "frontend"),
    ("AI Engineer", "ai"),
    ("Voice Engineer", "voice"),
    ("Audio Engineer", "voice"),
    ("Voice AI Engineer", "voice"),
    ("Speech ML Engineer", "voice"),
    ("Speech Machine Learning Engineer", "voice"),
    ("Speech Engineer", "voice"),
    ("Senior Backend Developer", None),
    ("Software Engineer", None),
    ("Full-stack AI Engineer", "ai"),
    (None, None),
])
@pytest.mark.parametrize("candidate_work", [
    "Shipped production voice-agent tool calling.",
    "Built frontend interfaces for an AI product.",
    "Owned full-stack features from design through launch.",
])
def test_persisted_role_uses_posting_title_only(monkeypatch, title, expected, candidate_work):
    annotation = structured_annotation("synthetic-role")
    for reason in annotation["reasons"][:2]:
        reason["detail"] = candidate_work
    original = deepcopy(annotation)
    captured = persistence._Inputs(
        {
            "id": "synthetic-role", "title": title,
            "raw_jd": "Build APIs. Work alongside frontend, AI and voice teams.",
            "company": "Voice AI Example",
        },
        {"candidate.positioning": candidate_work}, [], "a" * 64, "b" * 64, "c" * 64,
    )
    monkeypatch.setattr(persistence, "_capture", lambda *_args, **_kwargs: captured)

    class Connection:
        inserted = None

        def transaction(self):
            return nullcontext()

        def execute(self, sql, params=()):
            if sql.startswith("insert into public.posting_scores"):
                self.inserted = params
                return self
            return self

        def fetchone(self):
            return None if self.inserted is None else ("synthetic-role",)

    connection = Connection()
    result = core.ScoringResult(annotation, "synthetic", "synthetic-model")
    assert persistence._store(connection, captured, result) == "stored"
    stored = connection.inserted
    assert json.loads(stored[3]) == {
        "role_type": expected, "seniority_match": "positive",
        "remote_ok": "unknown", "red_flag_count": 0,
    }
    assert stored[1] == original["fit_score"]
    assert json.loads(stored[2]) == original["reasons"]
    assert json.loads(stored[-1]) == original
    assert annotation == original


@pytest.mark.parametrize("title, expected", [
    ("Senior Front-End Power Engineer", None),
    ("Front-End Integration Engineer", None),
    ("Senior Front-End CAD Engineer", None),
    ("Frontend Sales Engineer", None),
    ("Frontend Product Manager", None),
    ("Full Stack Integration Engineer", None),
    ("Frontend", None),
    ("Full Stack", None),
    ("Senior Frontend Software Engineer", "frontend"),
    ("Front End Web Applications Developer", "frontend"),
    ("Software Engineer II - Front-End", "frontend"),
    ("Senior Software Engineer, Full Stack", "fullstack"),
    ("Full Stack Software Developer", "fullstack"),
    ("Full Stack AI Engineer", "ai"),
    ("Frontend Voice AI Engineer", None),
    ("Full Stack Voice AI Engineer", None),
])
def test_role_requires_software_occupation(title, expected):
    assert persistence._labels(structured_annotation("synthetic-role"), {"title": title})[
        "role_type"
    ] == expected


@pytest.mark.parametrize("specialty", ["AI", "ML", "Machine Learning"])
@pytest.mark.parametrize("title", [
    "System Validation Engineer - Multiple Levels ({specialty} Fabric Products)",
    "Data Center Engineer, Compute and {specialty}",
    "Sales Engineer ({specialty} Software Engineer Tools)",
    "{specialty} Validation Engineer",
    "{specialty} Sales Engineer",
    "{specialty} Developer Relations Manager",
    "Validation Engineer and {specialty}",
    "Data Center Engineer for {specialty}",
    "Sales Engineer of {specialty} Products",
    "Sales Engineer in {specialty}",
    "Sales Engineer for {specialty} Software Engineer Tools",
    "Sales Engineer & {specialty} Engineer",
])
def test_ai_requires_primary_software_occupation(title, specialty):
    posting = {"title": title.format(specialty=specialty)}
    assert persistence._labels(structured_annotation("synthetic-role"), posting)[
        "role_type"
    ] is None


@pytest.mark.parametrize("title", [
    "AI Engineer", "ML Engineer", "Machine Learning Engineer",
    "AI Software Engineer", "Applied AI Engineer", "AI Researcher", "AI Developer",
    "Senior AI Software Engineer", "Principal ML Researcher", "LLM Engineer",
    "Artificial Intelligence Developer", "AI Engineer, Applied Research",
    "AI Engineer II - Applications", "AI Engineer (Remote)",
    "AI/ML Engineer", "ML / AI Software Engineer",
])
def test_ai_occupational_heads_remain_known(title):
    assert persistence._labels(structured_annotation("synthetic-role"), {"title": title})[
        "role_type"
    ] == "ai"


@pytest.mark.parametrize("domain", [
    "hardware", "chip", "RTL", "power", "silicon", "analog", "ASIC", "FPGA",
])
@pytest.mark.parametrize("role", ["Frontend", "Full Stack", "AI", "Voice AI"])
def test_hardware_domain_vetoes_even_a_software_head(domain, role):
    title = f"{role} Software Engineer - {domain}"
    assert persistence._labels(structured_annotation("synthetic-role"), {"title": title})[
        "role_type"
    ] is None


@pytest.mark.parametrize("title", [
    "AI Platform Engineer",
    "Principal Software Engineer (ML Infrastructure)",
    "Software Development Engineer, Recommendations AI, Commerce",
    "Staff Software & AI Engineer",
    "Software Engineer - AI Compiler",
    "Software Engineer - Agentic AI & Data",
    "AI Security - Senior Software Engineer",
    "Software Engineer (Example AI)",
    "Sr Software Engineer, Example AI",
    "AI Security Engineer",
    "Forward Deployed Engineer (FDE) - AI Transformation",
    "AI & Software Engineer (12345)",
    "AI SW Engineer",
    "Manager, Software Engineering - ML Infrastructure",
    "AI Data Engineer",
    "Software Engineer - Verification AI Infrastructure",
    "AI Systems Engineer",
    "Software Engineer - Kubernetes AI Foundations",
    "Software Engineer, AI Agent Platforms",
    "DevOps Engineer, AI Agent Platforms",
    "Data and AI Solutions Engineer",
    "AI Solutions Engineer",
    "AI Developer Technology Engineer",
    "C++ Software Engineer - AI Developer Tools",
    "AI and LLM Solutions Software Engineer",
    "Software Engineer, Tools, Automation and AI",
    "Cybersecurity AI Solutions Engineer",
    "AI Network Simulation Software Engineer",
    "Software Engineer, LLM Inference",
    "Software Engineer (Secure Agentic AI - Example City)",
    "Sr. AI Backend & Data Engineer",
    "Computer Vision & AI Algorithm Developer",
    "Software Engineer, Core AI Software - Example City",
    "Forward Deployed Engineer (AI Enablement)",
    "Machine Learning Systems Engineer, ML Platform",
    "Founder Style AI Native Software Engineer",
    "Backend Engineer with AI Experience",
    "Software Engineer, AI Enablement",
    "Backend Engineer - AI Team - Example Product",
    "AI Solutions Developer",
    "Backend Engineer - GenAI",
    "Full Stack Engineer (AI)",
    "AI Agents Developer",
    "Software Architect - Agentic Platform",
    "Frontend Developer, LLM Applications",
    "Software Engineer, Agents Platform",
    "AI-Native Software Engineer",
    "Software Engineer, AI-Powered Applications",
    "Backend Developer - AI-Assisted Search",
])
def test_ai_software_occupation_with_attached_specialisation(title):
    assert persistence._role_type(title) == "ai"


@pytest.mark.parametrize("title", [
    "System Validation Engineer - Multiple Levels (AI Fabric Products)",
    "Staff Software Engineer, AI Builder (Python)",
    "Data Center Engineer, HPC and AI",
    "Principal HPC and AI Operation Engineer",
    "Developer Relations Manager - AI Security",
    "Sales Engineer - AI/AppSec/Cloud Security",
    "AI-Driven 5G PHY SW Engineer",
    "System Integration & Infrastructure Engineer (Storage for AI workloads)",
])
def test_review_correct_null_occupation_and_assistant_use_shapes(title):
    assert persistence._role_type(title) is None


@pytest.mark.parametrize("title", [
    "Software Engineer, AI Assisted Development",
    "AI-Powered Software Engineer",
    "Software Engineer (AI Fluent)",
    "Software Engineer using AI Coding Tools",
    "Sales Engineer - Software Engineer, AI Platforms",
    "Product Manager (AI Software Engineer Tools)",
    "AI Developer Relations Engineer",
    "AI Researcher Relations Manager",
    "AI Platform Engineer Tools Sales Manager",
    "Validation Software Engineer - AI Platform",
])
def test_ai_qualifiers_do_not_manufacture_software_specialisation(title):
    assert persistence._role_type(title) is None


@pytest.mark.parametrize("specialty", ["AI", "ML", "Machine Learning", "GenAI"])
def test_software_developer_tools_are_a_valid_ai_product(specialty):
    assert persistence._role_type(f"Software Engineer - {specialty} Developer Tools") == "ai"


@pytest.mark.parametrize("title", [
    "Voice GenAI Engineer", "Speech Agentic AI Engineer", "Audio LLM Engineer",
])
def test_voice_specialisation_still_precedes_ai(title):
    assert persistence._role_type(title) == "voice"
