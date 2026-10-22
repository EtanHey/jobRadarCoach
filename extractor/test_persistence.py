from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from uuid import uuid4

import pytest

from extractor import core, persistence
from extractor.test_salary import (
    P9C_SALARY_SPANS,
    P9D_SALARY_SPANS,
    PRECISION_PREVIOUS_SALARY_CASES,
    ROUND5_SALARY_CASES,
    ROUND6_SALARY_CASES,
    ROUND7_SALARY_SPANS,
    ROUND8_SALARY_CASES,
    expected_salary_facts,
)
from scraper.brain_contract import BrainTransportError
from scraper.database import persist_postings
from scraper.employer_identity import resolve_employer

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

def salary_facts(stored_facts: dict[str, object]) -> dict[str, object]:
    return {key: value for key, value in stored_facts.items() if key != "employer_identity"}


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
    expected["facts"]["employer_identity"] = resolve_employer("Original company", RAW_JD, "lane3d")
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
    assert durable_state(connection, posting_id)[11] == {
        **unknown, "employer_identity": resolve_employer("Original company", RAW_JD, "lane3d"),
    }


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


@pytest.mark.parametrize("mode_source", ["extracted", "structured", "location"])
def test_office_schedule_overrides_remote_mode_even_when_quote_omits_it(connection, mode_source):
    raw_jd = RAW_JD + "\nWe require three days a week in the office and two days at home."
    posting_id = insert_posting(connection, raw_jd)
    connection.execute(
        "update postings set work_mode='remote',work_mode_source=%s,remote=true where id=%s",
        (mode_source, posting_id),
    )
    facts = deepcopy(FACTS)
    facts["remote"] = {"value": None, "evidence_quote": None}
    persistence.persist_extraction(connection, posting_id, raw_jd, extraction(raw_jd=raw_jd, facts=facts))
    assert connection.execute(
        "select work_mode,work_mode_source,remote from postings where id=%s", (posting_id,),
    ).fetchone() == ("hybrid", "extracted", None)


@pytest.mark.parametrize('remote', [True, False])
def test_location_hybrid_survives_extraction_and_rescrape(connection, remote):
    raw_jd = RAW_JD if remote else RAW_JD.replace('Remote work is available', 'Office-based work is required')
    facts = deepcopy(FACTS)
    facts['remote'] = {'value': remote, 'evidence_quote': 'Remote work is available' if remote else 'Office-based work is required'}
    row = {'source': 'mode-order', 'id': 'hybrid', 'url': 'https://example.test/job',
           'title': 'Engineer', 'company': 'Example', 'location': 'Tel Aviv, Israel (Hybrid)', 'jd_text': raw_jd}
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


def test_employer_identity_is_additive_and_refreshes_legacy_extractions(connection):
    raw_jd = "**Monday.com** is the employer — EngRadar is a job radar, not a recruiter."
    posting_id = insert_posting(connection, raw_jd)
    connection.execute("update public.postings set company='EngRadar' where id=%s", (posting_id,))
    facts = {key: [] if key == 'stack' else {'value': None, 'evidence_quote': None} for key in FACTS}
    result = extraction(raw_jd=raw_jd, facts=facts)
    persistence.persist_extraction(connection, posting_id, raw_jd, result)
    stored = durable_state(connection, posting_id)[11]
    assert stored['employer_identity']['hiring_employer'] == 'Monday.com'
    assert {key: value for key, value in stored.items() if key != 'employer_identity'} == facts
    identity = {key: result[key] for key in ('brain', 'model', 'extractor_version', 'schema_sha256')}
    connection.execute("update public.posting_extractions set facts=facts-'employer_identity' where posting_id=%s", (posting_id,))
    assert not persistence.has_current_extraction(connection, posting_id, raw_jd, **identity)
    assert persistence.persist_extraction(connection, posting_id, raw_jd, result) == 'stored'
    assert persistence.has_current_extraction(connection, posting_id, raw_jd, **identity)
@pytest.mark.parametrize("existing", ["competitive salary", "Competitive Salary", None, "$180,000 annually"])
def test_nonnumeric_salary_persists_remark_and_clears_only_matching_boilerplate(
    connection, existing,
):
    from extractor.test_core import runner_for

    raw_jd = RAW_JD + " We offer competitive salary."
    posting_id = insert_posting(connection, raw_jd)
    connection.execute("update postings set salary=%s where id=%s", (existing, posting_id))
    candidate = deepcopy(FACTS)
    candidate["salary"] = {
        "value": "competitive salary", "evidence_quote": "competitive salary",
    }
    result = core.extract_posting({"raw_jd": raw_jd}, {}, runner=runner_for(candidate))
    assert persistence.persist_extraction(connection, posting_id, raw_jd, result) == "stored"
    salary, stored_facts = connection.execute(
        "select p.salary, e.facts from postings p join posting_extractions e "
        "on e.posting_id=p.id where p.id=%s", (posting_id,),
    ).fetchone()
    assert salary == (existing if existing == "$180,000 annually" else None)
    assert stored_facts["salary"] == {"value": None, "evidence_quote": None}
    assert stored_facts["salary_remark"] == "competitive salary"
    assert persistence.persist_extraction(connection, posting_id, raw_jd, result) == "unchanged"


@pytest.mark.parametrize("salary, numeric", [
    ("401k", False), ("competitive salary + 401k", False),
    ("2026", False), ("24/7", False), ("2 years", False),
    ("100% remote", False), ("3 days a week", False),
    ("שכר 35000 בחודש", True), ('35,000 ש״ח לחודש', True),
    ("35,000 שקלים בחודש", True), ("up to 180000", True),
    ("שכר 25,000-30,000 ₪", True), ("עד 35 אלף", True),
    ("₪30K", True), ("up to $200k", True), ("up to 150,000 EUR", True),
] + PRECISION_PREVIOUS_SALARY_CASES + ROUND5_SALARY_CASES + ROUND6_SALARY_CASES)
def test_salary_evidence_survives_extraction_and_database_readback(connection, salary, numeric):
    from extractor.test_core import runner_for

    raw_jd = RAW_JD + "\n" + salary
    posting_id = insert_posting(connection, raw_jd)
    connection.execute("update postings set salary=%s where id=%s", (salary, posting_id))
    candidate = deepcopy(FACTS)
    candidate["salary"] = {"value": salary, "evidence_quote": salary}
    result = core.extract_posting({"raw_jd": raw_jd}, {}, runner=runner_for(candidate))
    assert persistence.persist_extraction(connection, posting_id, raw_jd, result) == "stored"
    stored_salary, stored_facts = connection.execute(
        "select p.salary, e.facts from postings p join posting_extractions e "
        "on e.posting_id=p.id where p.id=%s", (posting_id,),
    ).fetchone()
    expected = expected_salary_facts(candidate, salary, numeric)
    assert stored_salary == expected["salary"]["value"]
    assert salary_facts(stored_facts) == expected
    assert persistence.persist_extraction(connection, posting_id, raw_jd, result) == "unchanged"


@pytest.mark.parametrize("existing", ["matching", None, "$180,000 annually"])
@pytest.mark.parametrize("salary, span", ROUND7_SALARY_SPANS + [
    pytest.param(salary, span, id=f"p9c-{index}")
    for index, (salary, span) in enumerate(P9C_SALARY_SPANS)
])
def test_round7_salary_span_persists(connection, salary, span, existing):
    from extractor.test_core import runner_for

    raw_jd = RAW_JD + "\n" + salary
    posting_id = insert_posting(connection, raw_jd)
    prior = salary if existing == "matching" else existing
    connection.execute("update postings set salary=%s where id=%s", (prior, posting_id))
    candidate = deepcopy(FACTS)
    candidate["salary"] = {"value": salary, "evidence_quote": salary}
    result = core.extract_posting({"raw_jd": raw_jd}, {}, runner=runner_for(candidate))
    assert persistence.persist_extraction(connection, posting_id, raw_jd, result) == "stored"
    stored_salary, stored_facts = connection.execute(
        "select p.salary, e.facts from postings p join posting_extractions e "
        "on e.posting_id=p.id where p.id=%s", (posting_id,),
    ).fetchone()
    assert stored_salary == (span if span else (None if prior == salary else prior))
    assert stored_facts["salary"]["value"] == span
    assert stored_facts.get("salary_remark") == (salary if span != salary else None)
    assert persistence.persist_extraction(connection, posting_id, raw_jd, result) == "unchanged"


@pytest.mark.parametrize("quote, value, remark, span", ROUND8_SALARY_CASES)
def test_round8_case_insensitive_salary_persists_other_facts(connection, quote, value, remark, span):
    from extractor.test_core import runner_for

    raw_jd = RAW_JD + "\n" + quote
    posting_id = insert_posting(connection, raw_jd)
    connection.execute("update postings set salary=null where id=%s", (posting_id,))
    candidate = deepcopy(FACTS)
    candidate["salary"] = {"value": value, "evidence_quote": quote}
    result = core.extract_posting({"raw_jd": raw_jd}, {}, runner=runner_for(candidate))
    assert persistence.persist_extraction(connection, posting_id, raw_jd, result) == "stored"
    state = durable_state(connection, posting_id)
    assert state[:5] == ("Tel Aviv", True, "Senior", ["TypeScript"], span)
    expected = deepcopy(candidate)
    expected["salary"] = {"value": span, "evidence_quote": quote if span else None}
    expected["salary_remark"] = remark
    assert salary_facts(state[11]) == expected
    assert persistence.persist_extraction(connection, posting_id, raw_jd, result) == "unchanged"


@pytest.mark.parametrize("salary", [
    "Competitive salary; installed base: 120k",
    "Competitive salary; subscriber base = 250k",
    "Competitive salary; knowledge base contains 10k articles",
])
def test_review_base_counts_do_not_abort_other_fact_persistence(connection, salary):
    from extractor.test_core import runner_for

    raw_jd = RAW_JD + "\n" + salary
    posting_id = insert_posting(connection, raw_jd)
    connection.execute("update postings set salary=%s where id=%s", (salary, posting_id))
    candidate = deepcopy(FACTS)
    candidate["salary"] = {"value": salary, "evidence_quote": salary}
    result = core.extract_posting({"raw_jd": raw_jd}, {}, runner=runner_for(candidate))
    assert persistence.persist_extraction(connection, posting_id, raw_jd, result) == "stored"
    state = durable_state(connection, posting_id)
    assert state[:5] == ("Tel Aviv", True, "Senior", ["TypeScript"], None)
    expected = deepcopy(candidate)
    expected["salary"] = {"value": None, "evidence_quote": None}
    expected["salary_remark"] = salary
    assert salary_facts(state[11]) == expected
    assert persistence.persist_extraction(connection, posting_id, raw_jd, result) == "unchanged"


@pytest.mark.parametrize("existing", ["matching", "case-variant", None, "$180,000 annually"])
@pytest.mark.parametrize("salary, span", P9D_SALARY_SPANS)
def test_list_governor_salary_persists_other_facts(connection, salary, span, existing):
    from extractor.test_core import runner_for

    raw_jd = RAW_JD + "\n" + salary
    posting_id = insert_posting(connection, raw_jd)
    prior = salary if existing == "matching" else salary.upper() if existing == "case-variant" else existing
    connection.execute("update postings set salary=%s where id=%s", (prior, posting_id))
    candidate = deepcopy(FACTS)
    candidate["salary"] = {"value": salary, "evidence_quote": salary}
    result = core.extract_posting({"raw_jd": raw_jd}, {}, runner=runner_for(candidate))
    assert persistence.persist_extraction(connection, posting_id, raw_jd, result) == "stored"
    state = durable_state(connection, posting_id)
    rejected_prior = isinstance(prior, str) and prior.lower() == salary.lower()
    expected_salary = span if span else (None if rejected_prior else prior)
    assert state[:5] == ("Tel Aviv", True, "Senior", ["TypeScript"], expected_salary)
    expected = deepcopy(candidate)
    expected["salary"] = {"value": span, "evidence_quote": salary if span else None}
    if span != salary:
        expected["salary_remark"] = salary
    assert salary_facts(state[11]) == expected
    assert persistence.persist_extraction(connection, posting_id, raw_jd, result) == "unchanged"
