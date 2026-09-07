"""Bounded database-backed classifier batch."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping, Sequence
import json
import os
from typing import Protocol
from uuid import UUID

from classifier.persistence import list_scoring_candidates, score_and_persist
from scraper.brain import run_brain
from scraper.brain_contract import UnsupportedBrainError, resolve_brain


MAX_BATCH_SIZE = 30
MAX_TIMEOUT_SECONDS = 120
IMPLEMENTED_BRAINS = frozenset({"ollama", "codex"})
BRAIN_SETTINGS = (
    "BRAIN", "OLLAMA_BASE_URL", "OLLAMA_MODEL", "CODEX_MODEL", "CODEX_REASONING_EFFORT",
)


class Result(Protocol):
    def fetchone(self) -> tuple[object, ...] | None: ...


class Connection(Protocol):
    def execute(self, query: str, params: tuple[object, ...] = ()) -> Result: ...


def _log(**fields: object) -> None:
    print(json.dumps(fields, ensure_ascii=True, separators=(",", ":"), sort_keys=True), flush=True)


def load_runtime_profile(connection: Connection) -> dict[str, object]:
    row = connection.execute(
        "select value from public.profile where field = 'runtime.brain'"
    ).fetchone()
    return {} if row is None else {"runtime.brain": row[0]}


def _selection(
    connection: Connection,
    *,
    limit: int,
    posting_ids: Sequence[str],
    candidate_lister: Callable[..., list[str]],
) -> list[str]:
    return candidate_lister(
        connection, limit=limit, posting_ids=list(dict.fromkeys(posting_ids))
    )


def _provenance(
    connection: Connection, posting_id: str, selected_provider: str
) -> dict[str, object]:
    row = connection.execute(
        "select brain, model from public.posting_scores where posting_id = %s",
        (posting_id,),
    ).fetchone()
    if (
        row is not None
        and len(row) == 2
        and all(isinstance(value, str) and value.strip() for value in row)
    ):
        return {"provider": row[0], "model": row[1]}
    return {"provider": selected_provider}


def run_batch(
    connection: Connection,
    *,
    limit: int,
    timeout_seconds: int | float,
    posting_ids: Sequence[str] = (),
    env: Mapping[str, str] | None = None,
    candidate_lister: Callable[..., list[str]] = list_scoring_candidates,
    scorer: Callable[..., str] = score_and_persist,
    brain: Callable[..., object] = run_brain,
) -> int:
    """Score one bounded eligible batch and return nonzero after any failure."""

    if type(limit) is not int or not 1 <= limit <= MAX_BATCH_SIZE:
        raise ValueError("batch limit must be between 1 and 30")
    if (
        type(timeout_seconds) not in (int, float)
        or not 0 < timeout_seconds <= MAX_TIMEOUT_SECONDS
    ):
        raise ValueError("timeout must be between 0 and 120 seconds")
    profile = load_runtime_profile(connection)
    source_settings = os.environ if env is None else env
    settings = {key: source_settings[key] for key in BRAIN_SETTINGS if key in source_settings}
    provider = resolve_brain(profile, settings)
    if provider not in IMPLEMENTED_BRAINS:
        _log(selected=0, scored=0, failed=1, provider=provider,
             failure=UnsupportedBrainError.__name__)
        return 1
    settings["BRAIN"] = provider
    candidates = _selection(
        connection,
        limit=limit,
        posting_ids=posting_ids,
        candidate_lister=candidate_lister,
    )
    _log(selected=len(candidates), provider=provider)

    def brain_runner(request, profile_snapshot):
        return brain(
            request,
            profile_snapshot,
            env=settings,
            timeout_seconds=timeout_seconds,
        )

    scored = failed = 0
    for posting_id in candidates:
        try:
            outcome = scorer(connection, posting_id, brain_runner=brain_runner)
            if outcome in ("failed", "stale"):
                failed += 1
                failure = "ScoringFailed" if outcome == "failed" else "StaleInputs"
                _log(posting_id=posting_id, provider=provider,
                     outcome=outcome, failure=failure)
                continue
            if outcome not in ("stored", "unchanged"):
                raise RuntimeError("classifier persistence returned an unsupported outcome")
            scored += 1
            _log(posting_id=posting_id, outcome=outcome,
                 **_provenance(connection, posting_id, provider))
        except Exception as error:  # Preserve earlier commits and continue the batch.
            failed += 1
            _log(posting_id=posting_id, provider=provider, failure=type(error).__name__)
    _log(selected=len(candidates), scored=scored, failed=failed, provider=provider)
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
    if not 0 < parsed <= MAX_TIMEOUT_SECONDS:
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
        _log(selected=0, scored=0, failed=1, failure="MissingDatabaseURL")
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
        _log(selected=0, scored=0, failed=1, failure=type(error).__name__)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
