from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from scripts import local_analysis

try:
    import psycopg
except ImportError:
    psycopg = None

MIGRATIONS = Path(__file__).parents[1] / "supabase/migrations"
POSTING_ID = "00000000-0000-0000-0000-00000000a001"


def test_failed_item_is_deferred_without_a_tight_retry(monkeypatch, capsys) -> None:
    claims = iter([1, None])
    deferred = []
    monkeypatch.setattr(
        local_analysis, "_candidate_ids",
        lambda _connection, stage: [POSTING_ID] if stage == "extract" else [],
    )
    monkeypatch.setattr(local_analysis, "claim", lambda *_args: next(claims))
    monkeypatch.setattr(local_analysis, "_run_stage", lambda *_args: 1)
    monkeypatch.setattr(
        local_analysis, "defer", lambda *args: deferred.append(args[1:]) or True,
    )

    assert local_analysis.run_cycle(
        object(), max_items=2, timeout_seconds=120, lease_seconds=900,
        worker_id=str(uuid4()),
    ) == 1
    assert len(deferred) == 1
    records = [__import__("json").loads(line) for line in capsys.readouterr().out.splitlines()]
    assert records[-1] == {"attempted": 1, "event": "summary", "failed": 1}


def test_launcher_injects_database_url_without_putting_it_in_argv() -> None:
    launcher = (Path(__file__).parent / "run_local_analysis.sh").read_text()
    assert "run --env-file" in launcher and "DATABASE_URL" not in launcher
    assert '2>>"${diagnostic_log}"' in launcher


@pytest.fixture(scope="module")
def database_url():
    if psycopg is None:
        pytest.skip("psycopg is unavailable")
    from test_support.postgres import DatabaseUnavailable, migrated_database

    try:
        with migrated_database(MIGRATIONS, through=12) as url:
            yield url
    except DatabaseUnavailable as error:
        pytest.skip(str(error))


def seed_posting(connection) -> str:
    posting_id = str(uuid4())
    connection.execute(
        "insert into public.postings(id,source,external_id,url,title,company,raw_jd) "
        "values(%s,'local-analysis-test',%s,'https://example.test/job','Engineer',"
        "'Example',repeat('A substantive synthetic job description for lease testing. ',4))",
        (posting_id, posting_id),
    )
    return posting_id


def test_claim_is_exclusive_and_expired_work_is_recoverable(
    database_url, monkeypatch,
) -> None:
    first_worker, second_worker = str(uuid4()), str(uuid4())
    with psycopg.connect(database_url, autocommit=True) as first, psycopg.connect(
        database_url, autocommit=True
    ) as second:
        posting_id = seed_posting(first)

        assert local_analysis.claim(first, "extract", posting_id, first_worker, 180) == 1
        assert local_analysis.claim(second, "extract", posting_id, second_worker, 180) is None
        ready_id = seed_posting(first)
        monkeypatch.setattr(local_analysis, "MAX_SCAN", 1)
        assert [row for row in local_analysis._candidate_ids(first, "extract")] == [ready_id]
        first.execute(
            "update public.local_analysis_leases set lease_expires_at=clock_timestamp()-interval '1 second' "
            "where stage='extract' and posting_id=%s",
            (posting_id,),
        )
        assert local_analysis.claim(second, "extract", posting_id, second_worker, 180) == 2


def test_failure_is_backed_off_then_can_complete_once(database_url) -> None:
    worker = str(uuid4())
    with psycopg.connect(database_url, autocommit=True) as connection:
        posting_id = seed_posting(connection)
        assert local_analysis.claim(connection, "score", posting_id, worker, 180) == 1

        assert local_analysis.defer(connection, "score", posting_id, worker, "InvalidOutput")
        assert local_analysis.claim(connection, "score", posting_id, worker, 180) is None
        row = connection.execute(
            "select last_failure, next_attempt_at > clock_timestamp() "
            "from public.local_analysis_leases where stage='score' and posting_id=%s",
            (posting_id,),
        ).fetchone()
        assert row == ("InvalidOutput", True)

        connection.execute(
            "update public.local_analysis_leases set next_attempt_at=clock_timestamp()-interval '1 second' "
            "where stage='score' and posting_id=%s",
            (posting_id,),
        )
        assert local_analysis.claim(connection, "score", posting_id, worker, 180) == 2
        assert local_analysis.complete(connection, "score", posting_id, worker)
        assert not local_analysis.complete(connection, "score", posting_id, worker)
