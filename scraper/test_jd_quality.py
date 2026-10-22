"""Synthetic structural evidence; ambiguous descriptions must remain unflagged."""
from contextlib import nullcontext
import json

import pytest

from scraper import relevance


TEMPLATE = (
    "We are seeking a skilled [Job Title] to join our team.\n\n"
    "Qualifications: At least [number] years of professional experience."
)
MIXED = (
    "What role are you interested in? *\n\nEngineer\n\nManager\n\n"
    "As a Frontend Engineer at Example, you'll build customer interfaces.\n\n"
    "As Example's first Support Manager, you'll lead our support team."
)
EXTERNAL = (
    "Example is looking for a Software Engineer to join our team in Example City. "
    "Graduates are welcome to apply and help build a useful product.\n\n"
    "Read the job description here: https://example.test/full-jd\n\n"
    "Application instructions are at the end of the document."
)
LISTING = (
    "## Open positions\n\n[Frontend Engineer](https://example.test/one)\n"
    "[Support Manager](https://example.test/two)"
)


@pytest.mark.parametrize("jd,rule", [
    (None, "missing-body"), (" \n\t", "missing-body"),
    (TEMPLATE, "unfilled-template"), (MIXED, "mixed-role"),
    (EXTERNAL, "external-summary"), (LISTING, "listing-only"),
])
@pytest.mark.parametrize("has_score", [False, True])
def test_quality_evidence_gates_even_a_previously_scored_posting(jd, rule, has_score):
    gate = relevance._classified_gate(("synthetic", "Frontend Engineer", jd, has_score, {}))
    assert gate["rule"] == f"jd-quality-{rule}"


@pytest.mark.parametrize("jd", [
    "Build accessible React interfaces and test them with users.",
    "Requirements are not stated; contact the team for details.",
    "Our open positions include engineers and designers. Build React interfaces.",
    "Use array[number] and [Job Title] as sample data in our documentation.",
    "We are seeking a [Job Title] to join our team. Five years required.",
    "At least [number] years of experience. Build React products.",
    MIXED.replace("What role are you interested in? *", "Mentoring and collaboration"),
    MIXED.replace("Support Manager", "Frontend Engineer").replace("first ", ""),
    "As a Frontend Engineer at Example, you'll build interfaces.\n\n"
    "Work with our Support Manager and founding designer.\nWhat role are you interested in?",
    LISTING + "\nYou will build accessible interfaces using React and TypeScript.",
    EXTERNAL + "\nRequirements\n3+ years with React and Node.js.",
    EXTERNAL + "\n- Build React interfaces\n- Own TypeScript APIs",
    "Build React interfaces and Node.js services. Three years of TypeScript required.\n\n"
    "Full details: https://example.test/full-jd",
    "Example is looking for a Software Engineer to join our team. "
    "Build React interfaces and Node.js APIs. Three years of TypeScript required.\n\n"
    "Read the job description here: https://example.test/full-jd\n\n"
    "Application instructions are at the end of the document.",
])
def test_ambiguous_or_substantive_descriptions_are_not_quality_rejections(jd):
    assert relevance._classified_gate(("synthetic", "Frontend Engineer", jd, True, {}))["rule"] is None


class GateConnection:
    """Capture gate writes without a database or production resources."""
    def __init__(self, row):
        self.row = row
        self.queries = []
        self.writes = []

    def transaction(self):
        return nullcontext()

    def execute(self, query, params=()):
        self.queries.append(query)
        if query.startswith("update public.postings"):
            self.writes.append(json.loads(params[0]))
        return self

    def fetchall(self):
        return [self.row]

    def fetchone(self):
        return self.row


def test_refresh_rechecks_quality_for_missing_and_previously_scored_rows():
    db = GateConnection(("synthetic", "Frontend Engineer", None, True, {}))
    relevance.refresh_gate(db, posting_ids=["synthetic"])
    assert db.writes[0]["rule"] == "jd-quality-missing-body"
    selection = db.queries[0]
    assert "p.raw_jd is not null" not in selection
    assert "p.raw_jd ilike" not in selection
    assert "st.status in" in selection  # Pursuit protection remains in SQL.
    assert "override" in selection


def test_repaired_jd_clears_quality_and_keeps_owner_request():
    gate = {"score_requested": True, "rule": "jd-quality-missing-body", "version": "old"}
    db = GateConnection(("synthetic", "Frontend Engineer", "Build React products.", True, gate))
    relevance.refresh_gate(db, posting_ids=["synthetic"])
    assert db.writes == [{**gate, "version": relevance.VERSION, "rule": None}]
