from __future__ import annotations

from copy import deepcopy
import hashlib
import json

import pytest

from extractor import core
from extractor.payload import build_payload
from scraper.brain_contract import BrainValidationError


RAW_JD = (
    "Senior Backend Engineer in Tel Aviv. Remote work is available. "
    "Build TypeScript services. Salary is 120,000 USD annually."
)
FACTS = {
    "location": {"value": "Tel Aviv", "evidence_quote": "Tel Aviv"},
    "remote": {"value": True, "evidence_quote": "Remote work is available"},
    "seniority": {"value": "Senior", "evidence_quote": "Senior Backend Engineer"},
    "stack": [{"value": "TypeScript", "evidence_quote": "TypeScript"}],
    "salary": {"value": "120,000 USD annually", "evidence_quote": "120,000 USD annually"},
}


def extraction(
    raw_jd: str = RAW_JD,
    facts: dict[str, object] | None = None,
) -> dict[str, object]:
    jd_sha256 = hashlib.sha256(raw_jd.encode()).hexdigest()
    identity = {
        "brain": "ollama",
        "extractor_version": "1.1",
        "jd_sha256": jd_sha256,
        "model": "qwen2.5:7b-instruct",
        "schema_sha256": core.EXTRACTION_SCHEMA_SHA256,
    }
    fingerprint = hashlib.sha256(
        json.dumps(identity, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()
    return {**identity, "facts": deepcopy(FACTS if facts is None else facts), "fingerprint": fingerprint}


def test_rejects_fingerprint_not_owned_by_identity() -> None:
    invalid = {**extraction(), "fingerprint": "0" * 64}

    with pytest.raises(ValueError, match="fingerprint"):
        build_payload(invalid, RAW_JD)


def test_rejects_semantically_invalid_evidence() -> None:
    invalid_facts = deepcopy(FACTS)
    invalid_facts["remote"] = {
        "value": True,
        "evidence_quote": "Remote work is not available",
    }
    raw_jd = RAW_JD.replace(
        "Remote work is available", "Remote work is not available"
    )

    with pytest.raises(BrainValidationError):
        build_payload(extraction(raw_jd, invalid_facts), raw_jd)


@pytest.mark.parametrize("field", ["location", "stack"])
def test_rejects_unknown_nested_fact_fields(field: str) -> None:
    invalid = extraction()
    fact = invalid["facts"][field]
    if isinstance(fact, list):
        fact = fact[0]
    fact["private_notes"] = "PRIVATE_FACT_SENTINEL"

    with pytest.raises(ValueError, match="shape"):
        build_payload(invalid, RAW_JD)


def test_rejects_self_consistent_foreign_schema_identity() -> None:
    from extractor.payload import fingerprint

    invalid = extraction()
    invalid["schema_sha256"] = "a" * 64
    invalid["fingerprint"] = fingerprint(
        invalid["brain"], invalid["model"], invalid["extractor_version"],
        invalid["schema_sha256"], invalid["jd_sha256"],
    )
    with pytest.raises(ValueError, match="schema"):
        build_payload(invalid, RAW_JD)
