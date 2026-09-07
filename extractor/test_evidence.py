from __future__ import annotations

import pytest

from extractor.evidence import validate_facts
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


@pytest.mark.parametrize("mutation", [
    lambda value: value["location"].update(
        value="Jerusalem", evidence_quote="Tel Aviv, Israel"
    ),
    lambda value: value["salary"].update(evidence_quote="$120,000 to $150,000"),
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
