from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4

import pytest

from extractor import core, persistence
from scraper.brain_contract import BrainTransportError


psycopg = pytest.importorskip("psycopg")

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


@pytest.fixture
def connection():
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        pytest.skip("DATABASE_URL is required for real extraction persistence tests")
    connection = psycopg.connect(database_url)
    connection.execute("select 1")
    migration = Path(__file__).resolve().parents[1] / "supabase/migrations/0005_extraction_metadata.sql"
    connection.execute(migration.read_text(encoding="utf-8"))
    try:
        yield connection
    finally:
        connection.rollback()
        connection.close()


def extraction(
    raw_jd: str = RAW_JD,
    facts: dict[str, object] | None = None,
    *,
    brain: str = "ollama",
    model: str = "qwen2.5:7b-instruct",
    version: str = "1.1",
    schema_sha256: str = core.EXTRACTION_SCHEMA_SHA256,
) -> dict[str, object]:
    jd_sha256 = hashlib.sha256(raw_jd.encode()).hexdigest()
    identity = {
        "brain": brain,
        "extractor_version": version,
        "jd_sha256": jd_sha256,
        "model": model,
        "schema_sha256": schema_sha256,
    }
    fingerprint = hashlib.sha256(
        json.dumps(identity, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()
    return {**identity, "facts": deepcopy(FACTS if facts is None else facts), "fingerprint": fingerprint}


def insert_posting(connection, raw_jd: str = RAW_JD) -> str:
    posting_id = str(uuid4())
    connection.execute(
        "insert into public.postings "
        "(id, source, external_id, url, title, company, location, remote, seniority, "
        "stack, salary, raw_jd, first_seen_at, last_seen_at, liveness) values "
        "(%s, 'lane3d', %s, 'https://example.test/job', 'Original title', "
        "'Original company', 'Original place', false, 'Original seniority', "
        "array['Original stack'], 'Original salary', %s, "
        "'2026-09-01T10:00:00Z', '2026-09-07T10:00:00Z', '{\"alive\":true}')",
        (posting_id, posting_id, raw_jd),
    )
    connection.execute(
        "insert into public.posting_status (posting_id, status) values (%s, 'saved')",
        (posting_id,),
    )
    connection.execute(
        "insert into public.posting_scores (posting_id, score, brain) values (%s, 77, 'test')",
        (posting_id,),
    )
    return posting_id


def durable_state(connection, posting_id: str) -> tuple[object, ...]:
    return connection.execute(
        "select p.location, p.remote, p.seniority, p.stack, p.salary, e.brain, e.model, "
        "e.extractor_version, e.schema_sha256, e.jd_sha256, e.fingerprint, e.facts, "
        "e.extracted_at, e.xmin::text from public.postings p left join "
        "public.posting_extractions e on e.posting_id = p.id where p.id = %s",
        (posting_id,),
    ).fetchone()


def protected_state(connection, posting_id: str) -> tuple[object, ...]:
    return connection.execute(
        "select p.source, p.external_id, p.url, p.title, p.company, p.raw_jd, "
        "p.first_seen_at, p.last_seen_at, p.liveness, s.status, ps.score "
        "from public.postings p join public.posting_status s on s.posting_id = p.id "
        "join public.posting_scores ps on ps.posting_id = p.id where p.id = %s",
        (posting_id,),
    ).fetchone()


def test_success_updates_fields_and_preserves_identity_history_and_status(connection) -> None:
    posting_id = insert_posting(connection)
    protected = protected_state(connection, posting_id)

    assert persistence.persist_extraction(
        connection, posting_id, RAW_JD, extraction()
    ) == "stored"
    assert protected_state(connection, posting_id) == protected
    state = durable_state(connection, posting_id)
    assert state[:5] == ("Tel Aviv", True, "Senior", ["TypeScript"], "120,000 USD annually")
    expected = extraction()
    assert state[5:12] == tuple(expected[key] for key in (
        "brain", "model", "extractor_version", "schema_sha256", "jd_sha256", "fingerprint", "facts"
    ))
    assert state[12] is not None


def test_unknown_facts_preserve_known_columns_but_remain_truthful_in_metadata(connection) -> None:
    posting_id = insert_posting(connection)
    unknown = {
        "location": {"value": None, "evidence_quote": None},
        "remote": {"value": None, "evidence_quote": None},
        "seniority": {"value": None, "evidence_quote": None},
        "stack": [],
        "salary": {"value": None, "evidence_quote": None},
    }

    assert persistence.persist_extraction(
        connection, posting_id, RAW_JD, extraction(facts=unknown)
    ) == "stored"
    assert durable_state(connection, posting_id)[:5] == (
        "Original place", False, "Original seniority", ["Original stack"], "Original salary"
    )
    assert durable_state(connection, posting_id)[11] == unknown


def test_exact_repeat_has_no_churn_and_currentness_requires_exact_observed_identity(connection) -> None:
    posting_id = insert_posting(connection)
    result = extraction()
    assert persistence.persist_extraction(connection, posting_id, RAW_JD, result) == "stored"
    before = durable_state(connection, posting_id)

    assert persistence.persist_extraction(connection, posting_id, RAW_JD, result) == "unchanged"
    assert durable_state(connection, posting_id) == before
    identity = {key: result[key] for key in (
        "brain", "model", "extractor_version", "schema_sha256"
    )}
    assert persistence.has_current_extraction(connection, posting_id, RAW_JD, **identity)
    for field, value in (
        ("brain", "codex"), ("model", "configured-not-observed"),
        ("extractor_version", "1.2"), ("schema_sha256", "a" * 64),
    ):
        changed = {**identity, field: value}
        assert not persistence.has_current_extraction(
            connection, posting_id, RAW_JD, **changed
        )
    assert not persistence.has_current_extraction(
        connection, posting_id, RAW_JD + " changed", **identity
    )


def test_changed_jd_race_causes_no_writes(connection) -> None:
    posting_id = insert_posting(connection)
    connection.execute(
        "update public.postings set raw_jd = %s where id = %s",
        (RAW_JD + " Concurrent edit.", posting_id),
    )
    before = durable_state(connection, posting_id)

    assert persistence.persist_extraction(
        connection, posting_id, RAW_JD, extraction()
    ) == "stale"
    assert durable_state(connection, posting_id) == before


def test_provider_failure_leaves_last_good_untouched(connection) -> None:
    posting_id = insert_posting(connection)
    good = extraction()
    assert persistence.persist_extraction(connection, posting_id, RAW_JD, good) == "stored"
    before = durable_state(connection, posting_id)

    with pytest.raises(BrainTransportError):
        core.extract_posting(
            {"raw_jd": RAW_JD}, {},
            runner=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                BrainTransportError("provider failed")
            ),
        )
    assert durable_state(connection, posting_id) == before
