from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

import pytest

from extractor import core, persistence
from scraper.brain_contract import BrainTransportError
from scraper.database import persist_postings

psycopg = pytest.importorskip("psycopg")
from test_support.postgres import DatabaseUnavailable, migrated_database

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
MIGRATIONS = Path(__file__).parents[1] / "supabase/migrations"


@pytest.fixture(scope="module")
def migrated_database_url():
    try:
        with migrated_database(MIGRATIONS, through=20) as url:
            yield url
    except DatabaseUnavailable as error:
        pytest.skip(str(error))


@pytest.fixture
def connection(migrated_database_url):
    connection = psycopg.connect(migrated_database_url)
    connection.execute("select 1")
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
        "insert into public.posting_status (posting_id, status) values (%s, 'worth_checking')",
        (posting_id,),
    )
    reasons: list[object] = []
    labels = {
        "role_type": None,
        "seniority_match": "unknown",
        "remote_ok": "unknown",
        "red_flag_count": 0,
    }
    score_payload = {
        "employer_type": "unknown",
        "seniority_real": None,
        "fit_score": 77,
        "fit_tier": "good",
        "recommendation": "review",
        "reasons": reasons,
        "fit_line": "Compatibility fixture score.",
        "fit_line_evidence_ids": [],
        "luna_status": "ok",
    }
    connection.execute(
        "insert into public.posting_scores (posting_id, score, reasons, labels, brain, "
        "model, scorer_version, posting_sha256, profile_sha256, history_sha256, "
        "score_payload) values (%s, 77, %s::jsonb, %s::jsonb, 'test', 'fixture', "
        "'test-1', %s, %s, %s, %s::jsonb)",
        (
            posting_id,
            json.dumps(reasons),
            json.dumps(labels),
            "a" * 64,
            "b" * 64,
            "c" * 64,
            json.dumps(score_payload),
        ),
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


def test_explicit_headquarters_role_location_survives_extraction_and_persistence(
    connection,
) -> None:
    from scraper.brain import BrainResult

    raw_jd = (
        "This is a **full-time** position, based at our headquarters in **Harbor City**. "
        "Build reliable backend services with the engineering team."
    )
    facts = {
        field: {"value": None, "evidence_quote": None}
        for field in ("location", "remote", "seniority", "salary")
    }
    facts["stack"] = []
    facts["location"] = {
        "value": "Harbor City",
        "evidence_quote": "based at our headquarters in **Harbor City**",
    }
    posting_id = insert_posting(connection, raw_jd)

    def runner(request, *_args, **_kwargs):
        return BrainResult(facts, "codex", "fixture-model", request=request)

    result = core.extract_posting({"raw_jd": raw_jd}, {}, runner=runner)
    assert persistence.persist_extraction(connection, posting_id, raw_jd, result) == "stored"
    stored = connection.execute(
        "select p.location, e.extractor_version, e.facts from public.postings p "
        "join public.posting_extractions e on e.posting_id = p.id where p.id = %s",
        (posting_id,),
    ).fetchone()
    assert stored == ("Harbor City", core.EXTRACTOR_VERSION, facts)


def protected_state(connection, posting_id: str) -> tuple[object, ...]:
    return connection.execute(
        "select p.source, p.external_id, p.url, p.title, p.company, p.raw_jd, "
        "p.first_seen_at, p.last_seen_at, p.liveness, s.status, ps.score "
        "from public.postings p join public.posting_status s on s.posting_id = p.id "
        "join public.posting_scores ps on ps.posting_id = p.id where p.id = %s",
        (posting_id,),
    ).fetchone()


@pytest.mark.parametrize("jd", [
    "This job is based in Cedar Bay, with no option to work from our Harbor City headquarters.",
    "This job is based in Cedar Bay; another position is based at our headquarters in Harbor City.",
])
def test_unoffered_location_cannot_replace_structured_location(connection, jd) -> None:
    from extractor.evidence import ExtractionValidationError
    from scraper.brain import BrainResult

    raw_jd = jd + " Build reliable backend services with the engineering team."
    posting_id = insert_posting(connection, raw_jd)
    connection.execute(
        "update public.postings set location=%s where id=%s", ("Cedar Bay", posting_id),
    )
    before = durable_state(connection, posting_id)
    candidate = {
        field: {"value": None, "evidence_quote": None}
        for field in ("location", "remote", "seniority", "salary")
    }
    candidate["stack"] = []
    candidate["location"] = {"value": "Harbor City", "evidence_quote": "Harbor City"}

    def runner(request, *_args, **_kwargs):
        return BrainResult(candidate, "codex", "fixture-model", request=request)

    try:
        result = core.extract_posting(
            {"raw_jd": raw_jd, "location": "Cedar Bay"}, {}, runner=runner,
        )
        persistence.persist_extraction(connection, posting_id, raw_jd, result)
    except ExtractionValidationError as error:
        assert (error.category, error.field) == ("location_context", "location")
    assert durable_state(connection, posting_id) == before


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


def test_extraction_cannot_flip_structured_hybrid_to_remote(connection):
    posting_id = insert_posting(connection)
    connection.execute("update postings set work_mode='hybrid', work_mode_source='structured', remote=null where id=%s", (posting_id,))
    persistence.persist_extraction(connection, posting_id, RAW_JD, extraction())
    assert connection.execute("select work_mode,work_mode_source,remote from postings where id=%s", (posting_id,)).fetchone() == ('hybrid', 'structured', None)


def test_extracted_hybrid_location_keeps_legacy_boolean_unknown(connection):
    raw_jd = RAW_JD.replace('Tel Aviv.', 'Tel Aviv (Hybrid).')
    posting_id = insert_posting(connection, raw_jd)
    facts = deepcopy(FACTS)
    facts['location'] = {'value': 'Tel Aviv (Hybrid)', 'evidence_quote': 'Tel Aviv (Hybrid)'}
    persistence.persist_extraction(connection, posting_id, raw_jd, extraction(raw_jd=raw_jd, facts=facts))
    assert connection.execute("select work_mode,remote from postings where id=%s", (posting_id,)).fetchone() == ('hybrid', None)


def test_fresh_extraction_updates_extracted_mode(connection):
    posting_id = insert_posting(connection)
    connection.execute("update postings set work_mode='on-site',work_mode_source='extracted' where id=%s", (posting_id,))
    persistence.persist_extraction(connection, posting_id, RAW_JD, extraction())
    assert connection.execute('select work_mode,work_mode_source,remote from postings where id=%s',(posting_id,)).fetchone() == ('remote','extracted',True)


@pytest.mark.parametrize('remote', [True, False])
def test_location_hybrid_survives_extraction_and_rescrape(connection, remote):
    raw_jd = RAW_JD if remote else RAW_JD.replace('Remote work is available', 'Office-based work is required')
    facts = deepcopy(FACTS)
    facts['remote'] = {'value': remote, 'evidence_quote': 'Remote work is available' if remote else 'Office-based work is required'}
    row = dict(source='mode-order', id='hybrid', url='https://example.test/job',
               title='Engineer', company='Example', location='Tel Aviv, Israel (Hybrid)', jd_text=raw_jd)
    posting_id = persist_postings(connection, [row], '2026-10-05T03:00:00Z')[0]
    expected = ('hybrid', 'location', None)
    query = 'select work_mode,work_mode_source,remote from postings where id=%s'
    assert connection.execute(query, (posting_id,)).fetchone() == expected
    persistence.persist_extraction(connection, posting_id, raw_jd, extraction(raw_jd=raw_jd, facts=facts))
    assert connection.execute(query, (posting_id,)).fetchone() == expected
    persist_postings(connection, [row], '2026-10-05T03:01:00Z')
    assert connection.execute(query, (posting_id,)).fetchone() == expected
    persistence.persist_extraction(connection, posting_id, raw_jd, extraction(raw_jd=raw_jd, facts=facts, version='1.2'))
    assert connection.execute(query, (posting_id,)).fetchone() == expected
