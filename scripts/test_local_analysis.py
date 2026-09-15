from __future__ import annotations

from pathlib import Path
import threading
import time
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


def test_embedding_failure_does_not_block_scoring(monkeypatch, capsys) -> None:
    monkeypatch.setattr(local_analysis.job_embeddings, "capture_posting", lambda *_: object())
    monkeypatch.setattr(
        local_analysis.job_embeddings, "embed_prepared",
        lambda *_: (_ for _ in ()).throw(RuntimeError("embedding failed")),
    )
    monkeypatch.setattr(local_analysis.classifier_job, "run_batch", lambda *_a, **_k: 0)

    assert local_analysis._run_stage(object(), "score", POSTING_ID, 30) == 0
    assert "EmbeddingFailed" in capsys.readouterr().out


def test_scoring_failure_does_not_discard_valid_embedding(monkeypatch) -> None:
    stored = []
    monkeypatch.setattr(local_analysis.job_embeddings, "capture_posting", lambda *_: object())
    monkeypatch.setattr(
        local_analysis.job_embeddings, "embed_prepared", lambda *_: stored.append(True) or "stored",
    )
    monkeypatch.setattr(
        local_analysis.classifier_job, "run_batch",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("score failed")),
    )

    with pytest.raises(RuntimeError, match="score failed"):
        local_analysis._run_stage(object(), "score", POSTING_ID, 30)
    assert stored == [True]


def test_scoring_and_lease_do_not_wait_for_embedding_timeout(monkeypatch) -> None:
    release = threading.Event()
    finished = threading.Event()
    timeout_logged = threading.Event()
    monkeypatch.setattr(local_analysis, "EMBEDDING_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr(local_analysis.job_embeddings, "capture_posting", lambda *_: object())

    def embed(*_args):
        release.wait(1)
        finished.set()
        return "stored"

    monkeypatch.setattr(local_analysis.job_embeddings, "embed_prepared", embed)
    monkeypatch.setattr(local_analysis.classifier_job, "run_batch", lambda *_a, **_k: 0)
    monkeypatch.setattr(
        local_analysis, "_log",
        lambda **fields: timeout_logged.set() if fields.get("outcome") == "timeout" else None,
    )

    assert local_analysis._run_stage(object(), "score", POSTING_ID, 30) == 0
    assert timeout_logged.wait(0.2)
    release.set()
    assert finished.wait(0.2)
    assert local_analysis._embedding_slot.acquire(timeout=0.2)
    local_analysis._embedding_slot.release()


def test_hung_backfill_scan_times_out_without_holding_cycle(monkeypatch) -> None:
    release = threading.Event()
    finished = threading.Event()
    records = []
    monkeypatch.setattr(local_analysis, "EMBEDDING_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr(local_analysis, "_candidate_ids", lambda *_: [])

    def embed_missing(*_args, **_kwargs):
        release.wait(1)
        finished.set()
        return 0, 0

    monkeypatch.setattr(local_analysis.job_embeddings, "embed_missing", embed_missing)
    monkeypatch.setattr(local_analysis, "_log", lambda **fields: records.append(fields))
    started = time.monotonic()
    assert local_analysis.run_cycle(
        object(), max_items=1, timeout_seconds=30, lease_seconds=90,
        worker_id=str(uuid4()),
    ) == 0
    assert time.monotonic() - started < 0.2
    assert {"event": "embedding_scan", "outcome": "timeout"} in records
    release.set()
    assert finished.wait(0.2)
    assert local_analysis._embedding_slot.acquire(timeout=0.2)
    local_analysis._embedding_slot.release()


def test_local_main_initializes_sink_before_cycle(monkeypatch, tmp_path) -> None:
    events = []
    monkeypatch.setenv("DATABASE_URL", "postgresql://analysis@localhost/jobs")
    monkeypatch.setattr("sys.argv", ["local-analysis", "--lock-file", str(tmp_path / "lock")])
    monkeypatch.setattr(
        psycopg, "connect",
        lambda *_a, **_k: __import__("contextlib").nullcontext(object()),
    )
    monkeypatch.setattr(
        local_analysis.job_embeddings, "ensure_store", lambda: events.append("schema"),
        raising=False,
    )
    monkeypatch.setattr(
        local_analysis, "run_cycle", lambda *_a, **_k: events.append("cycle") or 0,
    )

    assert local_analysis.main() == 0
    assert events == ["schema", "cycle"]


def test_remote_url_skips_embedding_but_preserves_scoring(monkeypatch, tmp_path, capsys) -> None:
    lock = tmp_path / "analysis.lock"
    score_calls = []
    claims = iter([1, None])
    monkeypatch.setenv("DATABASE_URL", "postgresql://analysis@db.example.test/jobs")
    monkeypatch.setattr("sys.argv", ["local-analysis", "--lock-file", str(lock)])
    monkeypatch.setattr(
        psycopg, "connect",
        lambda *_a, **_k: __import__("contextlib").nullcontext(object()),
    )
    monkeypatch.setattr(
        local_analysis, "_candidate_ids",
        lambda _connection, stage: [POSTING_ID] if stage == "score" else [],
    )
    monkeypatch.setattr(local_analysis, "claim", lambda *_args: next(claims))
    monkeypatch.setattr(local_analysis, "complete", lambda *_args: True)
    monkeypatch.setattr(
        local_analysis.classifier_job, "run_batch",
        lambda *_a, **_k: score_calls.append(True) or 0,
    )
    def fail_embedding(*_args, **_kwargs):
        raise AssertionError("embedding must skip")

    for name in ("capture_posting", "embed_prepared", "embed_missing"):
        monkeypatch.setattr(
            local_analysis.job_embeddings, name, fail_embedding,
        )

    assert local_analysis.main() == 0
    assert score_calls == [True]
    records = [__import__("json").loads(line) for line in capsys.readouterr().out.splitlines()]
    assert sum(record == {"event": "embedding", "outcome": "skipped_remote_db"}
               for record in records) == 1


def test_launcher_uses_native_credential_boundary_without_secret_in_argv() -> None:
    launcher = (Path(__file__).parent / "run_local_analysis.sh").read_text()
    supervisor = (Path(__file__).parent / "local_analysis_supervisor.py").read_text()
    assert "scripts.local_analysis_supervisor" in launcher
    assert '"run"' in supervisor
    assert '"--env-file"' not in supervisor
    assert "DATABASE_URL" not in launcher
    assert "PGPASSWORD" not in launcher


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
