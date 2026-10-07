"""Synthetic cohort and #439 red-team replay through extraction and real writes."""

import json
from copy import deepcopy
from pathlib import Path

import pytest

from extractor import core, job, persistence
from extractor.evidence import ExtractionValidationError, validate_facts
from extractor.test_core import facts, runner_for
from extractor.test_persistence import connection, insert_posting, migrated_database_url
from scraper.brain_contract import BrainValidationError

ROWS = json.loads((Path(__file__).parent / "testdata/location_fallback.json").read_text())
OTHER_JD = "Senior Backend Engineer. Remote within Israel. Build TypeScript and Node.js API services. Salary: $120,000-$150,000 annually."
UNKNOWN = {"value": None, "evidence_quote": None}


def candidate_for(row, full_quote=False):
    candidate = facts()
    candidate["location"] = {
        "value": row["value"],
        "evidence_quote": row["jd"] if full_quote else row["quote"],
    }
    return candidate


@pytest.mark.parametrize("row", ROWS, ids=[row["name"] for row in ROWS])
@pytest.mark.parametrize("full_quote", [False, True], ids=["short-quote", "full-quote"])
def test_drop_location_preserves_facts_and_stops_retries(connection, row, full_quote, caplog):
    raw_jd = row["jd"] + " " + OTHER_JD
    candidate = candidate_for(row, full_quote)
    original = deepcopy(candidate)
    with pytest.raises(ExtractionValidationError) as rejected:
        validate_facts(candidate, raw_jd)
    assert (rejected.value.category, rejected.value.field) == ("location_context", "location")
    posting_id = insert_posting(connection, raw_jd)
    before = connection.execute("select location from postings where id=%s", (posting_id,)).fetchone()
    result = core.extract_posting({"raw_jd": raw_jd}, {}, runner=runner_for(candidate))
    expected = {**original, "location": UNKNOWN}
    assert result["facts"] == expected
    assert candidate == original
    assert caplog.messages == ["extraction_fact_dropped field=location category=location_context"]
    assert persistence.persist_extraction(connection, posting_id, raw_jd, result) == "stored"
    assert connection.execute("select location from postings where id=%s", (posting_id,)).fetchone() == before
    stored = connection.execute("select facts from posting_extractions where posting_id=%s", (posting_id,)).fetchone()[0]
    assert stored == expected
    assert job.select_postings(connection, limit=1, posting_ids=[posting_id]) == []
    assert persistence.persist_extraction(connection, posting_id, raw_jd, result) == "unchanged"


@pytest.mark.parametrize("failure", ["location_quote", "remote_quote", "seniority_quote", "salary_quote", "stack_quote", "stack_duplicate", "schema"])
def test_other_failures_still_reject(failure, caplog):
    row = ROWS[-1]
    candidate = candidate_for(row)
    if failure == "stack_duplicate":
        candidate["stack"].append(deepcopy(candidate["stack"][0]))
    elif failure == "schema":
        candidate["location"]["value"] = 7
    else:
        field = failure.removesuffix("_quote")
        fact = candidate[field][0] if field == "stack" else candidate[field]
        fact["evidence_quote"] = "ABSENT_PRIVATE_SENTINEL"
    with pytest.raises(BrainValidationError):
        core.extract_posting({"raw_jd": row["jd"] + " " + OTHER_JD}, {}, runner=runner_for(candidate))
    assert caplog.messages == []


def test_remote_consistency_after_drop_still_rejects(monkeypatch, caplog):
    row = ROWS[-1]
    candidate = candidate_for(row)
    candidate["remote"]["value"] = False
    monkeypatch.setattr(core, "derive_remote_fact", lambda *_: candidate["remote"])
    with pytest.raises(ExtractionValidationError) as rejected:
        core.extract_posting({"raw_jd": row["jd"] + " " + OTHER_JD}, {}, runner=runner_for(candidate))
    assert (rejected.value.category, rejected.value.field) == ("remote_consistency", "remote")
    assert caplog.messages == []


@pytest.mark.parametrize("value,jd", [
    ("Harbor City", "This job is based in Cedar Bay."),
    ("arbor", "This job is based in Harbor City."),
    ("Cit", "This job is based in Harbor City."),
])
def test_r1_absent_city_and_lexical_controls_still_reject(value, jd):
    candidate = facts()
    candidate["location"] = {"value": value, "evidence_quote": "Harbor City"}
    with pytest.raises(BrainValidationError):
        core.extract_posting({"raw_jd": jd + " " + OTHER_JD}, {}, runner=runner_for(candidate))
