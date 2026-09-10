#!/usr/bin/env python3
"""Drain a bounded hosted extraction/scoring backlog with expiring claims."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
from pathlib import Path
import re
from uuid import uuid4

from classifier import job as classifier_job
from classifier.persistence import list_scoring_candidates
from extractor import job as extractor_job

STAGES = ("extract", "score")
MAX_ITEMS = 30
MAX_SCAN = 1000
FAILURE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")


def _log(**fields: object) -> None:
    print(json.dumps(fields, separators=(",", ":"), sort_keys=True), flush=True)


def claim(connection, stage: str, posting_id: str, worker_id: str, lease_seconds: int):
    row = connection.execute(
        "insert into public.local_analysis_leases "
        "(stage,posting_id,worker_id,lease_expires_at,attempt_count) values "
        "(%s,%s,%s,clock_timestamp()+make_interval(secs=>%s),1) "
        "on conflict(stage,posting_id) do update set worker_id=excluded.worker_id, "
        "lease_expires_at=excluded.lease_expires_at, "
        "attempt_count=public.local_analysis_leases.attempt_count+1, "
        "last_failure=null, updated_at=clock_timestamp() "
        "where public.local_analysis_leases.lease_expires_at<=clock_timestamp() "
        "and public.local_analysis_leases.next_attempt_at<=clock_timestamp() "
        "returning attempt_count",
        (stage, posting_id, worker_id, lease_seconds),
    ).fetchone()
    return None if row is None else int(row[0])


def complete(connection, stage: str, posting_id: str, worker_id: str) -> bool:
    return connection.execute(
        "delete from public.local_analysis_leases where stage=%s and posting_id=%s "
        "and worker_id=%s returning posting_id", (stage, posting_id, worker_id),
    ).fetchone() is not None


def defer(connection, stage: str, posting_id: str, worker_id: str, failure: str) -> bool:
    if not FAILURE_RE.fullmatch(failure):
        raise ValueError("failure must be a safe category")
    return connection.execute(
        "update public.local_analysis_leases set lease_expires_at=clock_timestamp(), "
        "next_attempt_at=clock_timestamp()+make_interval(secs=>least(3600,"
        "60*power(2,least(attempt_count-1,6)))::double precision), "
        "last_failure=%s, updated_at=clock_timestamp() where stage=%s and posting_id=%s "
        "and worker_id=%s returning posting_id", (failure, stage, posting_id, worker_id),
    ).fetchone() is not None


def _safe_failure(error: Exception) -> str:
    name = type(error).__name__
    return name if FAILURE_RE.fullmatch(name) else "UnexpectedError"


def _candidate_ids(connection, stage: str) -> list[str]:
    if stage == "extract":
        return [str(row["id"]) for row in extractor_job.select_postings(
            connection, limit=MAX_SCAN, claimable_stage="extract"
        )]
    return list_scoring_candidates(connection, limit=MAX_SCAN, claimable_stage="score")


def _run_stage(connection, stage: str, posting_id: str, timeout_seconds: float) -> int:
    settings = {
        "BRAIN": "codex",
        "CODEX_MODEL": "gpt-5.6-luna" if stage == "extract" else "gpt-5.6-terra",
    }
    runner = extractor_job.run_batch if stage == "extract" else classifier_job.run_batch
    return runner(connection, limit=1, timeout_seconds=timeout_seconds,
                  posting_ids=(posting_id,), env=settings)


def run_cycle(connection, *, max_items: int, timeout_seconds: float,
              lease_seconds: int, worker_id: str) -> int:
    attempted = failed = 0
    stage_offset = 0
    while attempted < max_items:
        claimed = None
        for offset in range(len(STAGES)):
            stage = STAGES[(stage_offset + offset) % len(STAGES)]
            for posting_id in _candidate_ids(connection, stage):
                attempt = claim(connection, stage, posting_id, worker_id, lease_seconds)
                if attempt is not None:
                    claimed = stage, posting_id, attempt
                    stage_offset = (STAGES.index(stage) + 1) % len(STAGES)
                    break
            if claimed:
                break
        if claimed is None:
            break
        stage, posting_id, attempt = claimed
        attempted += 1
        _log(event="claimed", stage=stage, posting_id=posting_id, attempt=attempt)
        try:
            exit_code = _run_stage(connection, stage, posting_id, timeout_seconds)
        except Exception as error:
            exit_code = 1
            failure = _safe_failure(error)
        else:
            failure = "BatchFailed"
        if exit_code == 0:
            if complete(connection, stage, posting_id, worker_id):
                _log(event="completed", stage=stage, posting_id=posting_id)
            else:
                failed += 1
                _log(event="deferred", stage=stage, posting_id=posting_id,
                     failure="LeaseLost")
        else:
            failed += 1
            if not defer(connection, stage, posting_id, worker_id, failure):
                failure = "LeaseLost"
            _log(event="deferred", stage=stage, posting_id=posting_id, failure=failure)
    _log(event="summary", attempted=attempted, failed=failed)
    return 1 if failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-items", type=int, default=6)
    parser.add_argument("--timeout-seconds", type=float, default=120)
    parser.add_argument("--lease-seconds", type=int, default=900)
    parser.add_argument("--lock-file", type=Path, required=True)
    args = parser.parse_args()
    if not 1 <= args.max_items <= MAX_ITEMS or not 0 < args.timeout_seconds <= 120:
        parser.error("max-items must be 1..30 and timeout-seconds must be 0..120")
    if not args.timeout_seconds + 60 <= args.lease_seconds <= 3600:
        parser.error("lease-seconds must exceed timeout by 60 and be at most 3600")
    database_url = os.environ.get("DATABASE_URL", "").strip()
    if not database_url:
        _log(event="summary", attempted=0, failed=1, failure="MissingDatabaseURL")
        return 1
    os.umask(0o077)
    args.lock_file.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with args.lock_file.open("a", encoding="utf-8") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            _log(event="summary", attempted=0, failed=0, outcome="already_running")
            return 0
        try:
            import psycopg
            with psycopg.connect(database_url, autocommit=True) as connection:
                return run_cycle(connection, max_items=args.max_items,
                                 timeout_seconds=args.timeout_seconds,
                                 lease_seconds=args.lease_seconds,
                                 worker_id=str(uuid4()))
        except Exception as error:
            _log(event="summary", attempted=0, failed=1, failure=type(error).__name__)
            return 1


if __name__ == "__main__":
    raise SystemExit(main())
