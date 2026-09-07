from __future__ import annotations

import hashlib
import json
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from classifier import persistence
from classifier.test_core import profile_snapshot, wire_annotation
from scraper.annotate import RECOMMENDATIONS
from scraper.brain import BrainResult, BrainTransportError

psycopg = pytest.importorskip("psycopg")
from test_support.postgres import DatabaseUnavailable, migrated_database

RAW_JD = "Build a Full-stack TypeScript and React product with Node.js. " * 12
MIGRATIONS = Path(__file__).parents[1] / "supabase/migrations"


@pytest.fixture(scope="module")
def migrated_database_url():
    try:
        with migrated_database(MIGRATIONS, through=6) as url:
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


def seed(connection, *, status: str = "saved") -> str:
    posting_id = str(uuid4())
    connection.execute("delete from public.profile")
    for field, value in profile_snapshot().items():
        if field in {"people", "connectors"}:
            continue
        connection.execute(
            "insert into public.profile (field, value) values (%s, %s::jsonb)",
            (field, json.dumps(value)),
        )
    connection.execute(
        "insert into public.postings (id, source, external_id, url, title, company, "
        "location, raw_jd) values (%s, 'lane4b', %s, 'https://example.test/job', "
        "'Full-stack Engineer', 'Public Example', 'Tel Aviv', %s)",
        (posting_id, posting_id, RAW_JD),
    )
    connection.execute(
        "insert into public.posting_status (posting_id, status) values (%s, %s)",
        (posting_id, status),
    )
    jd_sha256 = hashlib.sha256(RAW_JD.encode()).hexdigest()
    connection.execute(
        "insert into public.posting_extractions (posting_id, brain, model, "
        "extractor_version, schema_sha256, jd_sha256, fingerprint, facts) values "
        "(%s, 'codex', 'configured:gpt-5.6-luna', 'test-1', %s, %s, %s, %s::jsonb)",
        (
            posting_id,
            "a" * 64,
            jd_sha256,
            "b" * 64,
            json.dumps(
                {
                    "location": {"value": None, "evidence_quote": None},
                    "remote": {"value": None, "evidence_quote": None},
                    "seniority": {"value": None, "evidence_quote": None},
                    "stack": [],
                    "salary": {"value": None, "evidence_quote": None},
                }
            ),
        ),
    )
    connection.execute(
        "insert into public.application_history "
        "(company, role, application_date, outcome) values "
        "('Prior Public Company', 'Frontend Engineer', '2026-01-15', 'withdrew')"
    )
    return posting_id


def runner_for(recommendation: str, *, fit_score: int = 72, fit_tier: str = "good"):
    def accepted(request, _profile):
        posting_id = request.output_schema["properties"]["reasons"]["properties"][
            "product_role_match"
        ]["properties"]["evidence_ids"]["items"]["enum"][0].removeprefix("posting:")
        response = wire_annotation(
            posting_id,
            recommendation=recommendation,
            fit_score=fit_score,
            fit_tier=fit_tier,
        )
        response["reasons"]["product_role_match"]["detail"] = (
            "The validated evidence supports a full-stack product role."
        )
        return BrainResult(
            response, "codex", "configured:gpt-5.6-luna", request=request
        )

    return accepted


runner = runner_for("apply")


def score_state(connection, posting_id: str):
    return connection.execute(
        "select score, reasons, labels, brain, model, scorer_version, "
        "posting_sha256, profile_sha256, history_sha256, score_payload, "
        "scored_at, xmin::text from public.posting_scores where posting_id = %s",
        (posting_id,),
    ).fetchone()


def test_first_write_is_coherent_and_exact_repeat_does_not_churn(connection) -> None:
    posting_id = seed(connection)
    identity = connection.execute(
        "select p.source, p.external_id, p.url, p.title, p.company, s.status "
        "from public.postings p join public.posting_status s on s.posting_id = p.id "
        "where p.id = %s",
        (posting_id,),
    ).fetchone()

    assert (
        persistence.score_and_persist(connection, posting_id, brain_runner=runner)
        == "stored"
    )
    first = score_state(connection, posting_id)
    assert first is not None
    assert first[:6] == (
        72,
        first[1],
        {
            "role_type": "fullstack",
            "seniority_match": "positive",
            "remote_ok": "unknown",
            "red_flag_count": 0,
        },
        "codex",
        "configured:gpt-5.6-luna",
        persistence.SCORER_VERSION,
    )
    assert first[9]["fit_score"] == first[0]
    assert first[9]["reasons"] == first[1]
    assert first[9]["fit_tier"] == "good"
    assert first[9]["recommendation"] == "apply"
    assert all(len(value) == 64 for value in first[6:9])

    assert (
        persistence.score_and_persist(connection, posting_id, brain_runner=runner)
        == "unchanged"
    )
    assert score_state(connection, posting_id) == first
    assert (
        connection.execute(
            "select p.source, p.external_id, p.url, p.title, p.company, s.status "
            "from public.postings p join public.posting_status s on s.posting_id = p.id "
            "where p.id = %s",
            (posting_id,),
        ).fetchone()
        == identity
    )


def test_migration_preserves_a_genuine_pre_migration_score() -> None:
    try:
        database = migrated_database(MIGRATIONS, through=5)
        with database as url, psycopg.connect(url) as connection:
            legacy_id = str(uuid4())
            connection.execute(
                "insert into public.postings (id, source, external_id, url, title, company) "
                "values (%s, 'lane4b-legacy', %s, 'https://example.test/legacy', "
                "'Legacy', 'Example')",
                (legacy_id, legacy_id),
            )
            connection.execute(
                "insert into public.posting_scores (posting_id, score, brain) "
                "values (%s, 11, 'legacy')",
                (legacy_id,),
            )
            connection.commit()
            connection.execute(
                (MIGRATIONS / "0006_scoring_metadata.sql").read_text(encoding="utf-8")
            )
            connection.commit()
            assert connection.execute(
                "select score, model, posting_sha256, score_payload "
                "from public.posting_scores where posting_id = %s",
                (legacy_id,),
            ).fetchone() == (11, None, None, None)
            posting_id = seed(connection)
            with pytest.raises(psycopg.errors.CheckViolation), connection.transaction():
                connection.execute(
                    "insert into public.posting_scores (posting_id, score, brain) "
                    "values (%s, 11, 'new')",
                    (posting_id,),
                )
    except DatabaseUnavailable as error:
        pytest.skip(str(error))


@pytest.mark.parametrize("recommendation", sorted(RECOMMENDATIONS))
def test_every_actual_recommendation_persists(connection, recommendation: str) -> None:
    posting_id = seed(connection)
    assert (
        persistence.score_and_persist(
            connection, posting_id, brain_runner=runner_for(recommendation)
        )
        == "stored"
    )
    assert score_state(connection, posting_id)[9]["recommendation"] == recommendation


def test_consider_is_rejected_before_persistence(connection) -> None:
    posting_id = seed(connection)
    assert (
        persistence.score_and_persist(
            connection, posting_id, brain_runner=runner_for("consider")
        )
        == "failed"
    )
    assert score_state(connection, posting_id) is None


def test_actual_stretch_tier_persists(connection) -> None:
    posting_id = seed(connection)
    assert (
        persistence.score_and_persist(
            connection,
            posting_id,
            brain_runner=runner_for("review", fit_score=50, fit_tier="stretch"),
        )
        == "stored"
    )
    assert score_state(connection, posting_id)[9]["fit_tier"] == "stretch"


@pytest.mark.parametrize(
    "query",
    [
        "update public.posting_scores set posting_sha256=null where posting_id=%s",
        "update public.posting_scores set profile_sha256=null where posting_id=%s",
        "update public.posting_scores set history_sha256=null where posting_id=%s",
        "update public.posting_scores set score_payload=null where posting_id=%s",
        (
            "update public.posting_scores set score_payload=jsonb_set(score_payload, "
            "'{recommendation}', 'null') where posting_id=%s"
        ),
        (
            "update public.posting_scores set labels=jsonb_set(labels, "
            "'{seniority_match}', 'null') where posting_id=%s"
        ),
    ],
)
def test_complete_metadata_constraint_fails_closed(connection, query: str) -> None:
    posting_id = seed(connection)
    assert (
        persistence.score_and_persist(connection, posting_id, brain_runner=runner)
        == "stored"
    )
    with pytest.raises(psycopg.errors.CheckViolation), connection.transaction():
        connection.execute(query, (posting_id,))
    assert score_state(connection, posting_id) is not None


@pytest.mark.parametrize("race", ["jd", "profile", "history"])
def test_changed_input_during_call_causes_no_write(connection, race: str) -> None:
    posting_id = seed(connection)

    def racing_runner(request, snapshot):
        if race == "jd":
            connection.execute(
                "update public.postings set raw_jd = raw_jd || ' changed' where id = %s",
                (posting_id,),
            )
        elif race == "profile":
            connection.execute(
                "update public.profile set value = '\"Changed positioning\"'::jsonb "
                "where field = 'candidate.positioning'"
            )
        else:
            connection.execute(
                "insert into public.application_history (company) values ('New history')"
            )
        return runner(request, snapshot)

    assert (
        persistence.score_and_persist(
            connection, posting_id, brain_runner=racing_runner
        )
        == "stale"
    )
    assert score_state(connection, posting_id) is None


def test_failed_output_preserves_last_good_score(connection) -> None:
    posting_id = seed(connection)
    assert (
        persistence.score_and_persist(connection, posting_id, brain_runner=runner)
        == "stored"
    )
    before = score_state(connection, posting_id)

    def failed(*_args):
        raise BrainTransportError("provider failed")

    assert (
        persistence.score_and_persist(connection, posting_id, brain_runner=failed)
        == "failed"
    )
    assert score_state(connection, posting_id) == before


def test_selection_is_unscored_plus_open_rows_on_profile_change_only(
    connection,
) -> None:
    unscored = seed(connection, status="saved")
    seen = seed(connection, status="seen")
    saved = seed(connection, status="saved")
    assert (
        persistence.score_and_persist(connection, seen, brain_runner=runner) == "stored"
    )
    assert (
        persistence.score_and_persist(connection, saved, brain_runner=runner)
        == "stored"
    )
    connection.execute(
        "update public.profile set value = '\"Changed positioning\"'::jsonb "
        "where field = 'candidate.positioning'"
    )

    selected = persistence.list_scoring_candidates(connection, limit=20)

    assert unscored in selected
    assert seen in selected
    assert saved not in selected


def test_explicit_eligible_id_beyond_general_scan_is_selected(connection) -> None:
    original = seed(connection)
    ids = [str(UUID(int=(1 << 128) - 1 - index)) for index in range(1002)]
    target = ids[0]
    with connection.cursor() as cursor:
        cursor.executemany(
            "insert into public.postings(id,source,external_id,url,title,company,raw_jd) "
            "values(%s,'candidate-boundary',%s,'https://example.test/job',"
            "'Engineer','Example',%s)", [(item, item, RAW_JD) for item in ids],
        )
        cursor.executemany(
            "insert into public.posting_status(posting_id,status) values(%s,'new')",
            [(item,) for item in ids],
        )
        cursor.executemany(
            "insert into public.posting_extractions(posting_id,brain,model,"
            "extractor_version,schema_sha256,jd_sha256,fingerprint,facts) "
            "select %s,brain,model,extractor_version,schema_sha256,jd_sha256,"
            "fingerprint,facts from public.posting_extractions where posting_id=%s",
            [(item, original) for item in ids],
        )
    assert target not in persistence.list_scoring_candidates(connection, limit=1000)
    assert persistence.list_scoring_candidates(
        connection, limit=1, posting_ids=[target, target]
    ) == [target]
    assert persistence.list_scoring_candidates(
        connection, limit=1, posting_ids=[str(uuid4())]
    ) == []
