"""Bounded database-backed structured extraction batch."""

from __future__ import annotations

import argparse
from functools import partial
from collections.abc import Callable, Mapping, Sequence
import json
import os
from typing import Protocol
from uuid import UUID

from extractor.core import (
    MAX_RAW_JD_BYTES,
    MAX_REQUEST_TIMEOUT_SECONDS,
    MIN_RAW_JD_CHARS,
    extract_posting,
)
from extractor.persistence import persist_extraction
from scraper.brain import run_brain
from scraper.brain_contract import UnsupportedBrainError, resolve_brain


MAX_BATCH_SIZE = 30
IMPLEMENTED_BRAINS = frozenset({"ollama", "codex"})


class Result(Protocol):
    def fetchall(self) -> list[tuple[object, ...]]: ...
    def fetchone(self) -> tuple[object, ...] | None: ...


class Connection(Protocol):
    def execute(self, query: str, params: tuple[object, ...] = ()) -> Result: ...


def _log(**fields: object) -> None:
    print(json.dumps(fields, ensure_ascii=True, separators=(",", ":"), sort_keys=True), flush=True)


def _assignment_fields(
    posting_ids: Sequence[str], selected_ids: Sequence[str], limit: int,
) -> dict[str, object]:
    requested = list(dict.fromkeys(posting_ids))
    selected = list(selected_ids)
    if not requested or len(requested) > limit:
        return {}
    if len(selected) != len(set(selected)) or not set(selected) <= set(requested):
        return {}
    selected_set = set(selected)
    skipped = [item for item in requested if item not in selected_set]
    return {
        "skipped": len(skipped),
        "selected_posting_ids": selected,
        "skipped_posting_ids": skipped,
    }


def load_runtime_profile(connection: Connection) -> dict[str, object]:
    """Capture only the committed provider-selection field needed by extraction."""

    row = connection.execute(
        "select value from public.profile where field = 'runtime.brain'"
    ).fetchone()
    return {} if row is None else {"runtime.brain": row[0]}


def select_postings(
    connection: Connection,
    *,
    limit: int,
    posting_ids: Sequence[str] = (),
) -> list[dict[str, object]]:
    """Select bounded substantive JDs that have no extraction receipt."""

    requested = list(dict.fromkeys(posting_ids)) or None
    rows = connection.execute(
        "select p.id::text, p.raw_jd from public.postings p "
        "where p.raw_jd is not null and p.raw_jd ~ '[^[:space:]]' "
        "and char_length(regexp_replace(p.raw_jd, "
        "'(^[[:space:]]+|[[:space:]]+$)', '', 'g')) >= %s "
        "and octet_length(p.raw_jd) <= %s "
        "and not exists (select 1 from public.posting_extractions e "
        "where e.posting_id = p.id) "
        "and (%s::uuid[] is null or p.id = any(%s::uuid[])) "
        "order by p.first_seen_at, p.id limit %s",
        (MIN_RAW_JD_CHARS, MAX_RAW_JD_BYTES, requested, requested, limit),
    ).fetchall()
    selected = []
    for posting_id, raw_jd in rows:
        if not isinstance(raw_jd, str) or len(raw_jd.strip()) < MIN_RAW_JD_CHARS:
            continue
        try:
            within_limit = len(raw_jd.encode("utf-8")) <= MAX_RAW_JD_BYTES
        except UnicodeEncodeError:
            continue
        if within_limit:
            selected.append({"id": str(posting_id), "raw_jd": raw_jd})
    return selected


def run_batch(
    connection: Connection,
    *,
    limit: int,
    timeout_seconds: int | float,
    posting_ids: Sequence[str] = (),
    env: Mapping[str, str] | None = None,
    extractor: Callable[..., dict[str, object]] | None = None,
    persister: Callable[..., str] = persist_extraction,
) -> int:
    """Run a bounded batch, returning nonzero after any typed row failure."""

    if type(limit) is not int or not 1 <= limit <= MAX_BATCH_SIZE:
        raise ValueError("batch limit must be between 1 and 30")
    if (
        type(timeout_seconds) not in (int, float)
        or not 0 < timeout_seconds <= MAX_REQUEST_TIMEOUT_SECONDS
    ):
        raise ValueError("timeout must be between 0 and 120 seconds")
    profile = load_runtime_profile(connection)
    settings = dict(os.environ if env is None else env)
    provider = resolve_brain(profile, settings)
    if extractor is None:
        extractor = partial(extract_posting, runner=partial(run_brain, env=settings))
    if provider not in IMPLEMENTED_BRAINS:
        _log(selected=0, extracted=0, failed=1, provider=provider,
             failure=UnsupportedBrainError.__name__)
        return 1
    postings = select_postings(connection, limit=limit, posting_ids=posting_ids)
    assignment = _assignment_fields(
        posting_ids, [str(posting["id"]) for posting in postings], limit,
    )
    _log(selected=len(postings), provider=provider)
    extracted = failed = 0
    for posting in postings:
        posting_id = str(posting["id"])
        raw_jd = str(posting["raw_jd"])
        try:
            result = extractor(posting, profile, timeout_seconds=timeout_seconds)
            outcome = persister(connection, posting_id, raw_jd, result)
            if outcome == "stale":
                failed += 1
                _log(posting_id=posting_id, provider=result["brain"], model=result["model"],
                     outcome="stale", failure="StaleJD")
                continue
            if outcome not in ("stored", "unchanged"):
                raise RuntimeError("persistence returned an unsupported outcome")
            extracted += 1
            _log(posting_id=posting_id, provider=result["brain"], model=result["model"],
                 outcome=outcome)
        except Exception as error:  # Keep later rows eligible; emit only the safe type.
            failed += 1
            _log(posting_id=posting_id, provider=provider, failure=type(error).__name__)
    _log(
        selected=len(postings), extracted=extracted, failed=failed,
        provider=provider, **assignment,
    )
    return 1 if failed else 0


def _bounded_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be an integer") from error
    if not 1 <= parsed <= MAX_BATCH_SIZE:
        raise argparse.ArgumentTypeError("must be between 1 and 30")
    return parsed


def _bounded_timeout(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be a number") from error
    if not 0 < parsed <= MAX_REQUEST_TIMEOUT_SECONDS:
        raise argparse.ArgumentTypeError("must be between 0 and 120")
    return parsed


def _posting_id(value: str) -> str:
    try:
        return str(UUID(value))
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be a UUID") from error


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", required=True, type=_bounded_int)
    parser.add_argument("--timeout-seconds", required=True, type=_bounded_timeout)
    parser.add_argument("--posting-id", action="append", default=[], type=_posting_id)
    args = parser.parse_args(argv)
    database_url = os.environ.get("DATABASE_URL", "").strip()
    if not database_url:
        _log(selected=0, extracted=0, failed=1, failure="MissingDatabaseURL")
        return 1
    try:
        import psycopg

        with psycopg.connect(database_url, autocommit=True) as connection:
            return run_batch(
                connection,
                limit=args.limit,
                timeout_seconds=args.timeout_seconds,
                posting_ids=args.posting_id,
            )
    except Exception as error:
        _log(selected=0, extracted=0, failed=1, failure=type(error).__name__)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
