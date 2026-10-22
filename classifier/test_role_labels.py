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
    ("Full-stack AI Engineer", None),
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
    ("Full Stack AI Engineer", None),
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
    "Software Engineer - {specialty} Developer Tools",
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
