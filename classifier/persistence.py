"""Race-safe persistence for validated classifier results."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Literal, Protocol

from classifier import core, projection

SCORER_VERSION = "1.0"
PersistOutcome = Literal["stored", "unchanged", "stale", "failed"]


class Result(Protocol):
    def fetchall(self) -> list[tuple[object, ...]]: ...
    def fetchone(self) -> tuple[object, ...] | None: ...


class Connection(Protocol):
    def execute(self, query: str, params: tuple[object, ...] = ()) -> Result: ...
    def transaction(self) -> AbstractContextManager[object]: ...


@dataclass(frozen=True)
class _Inputs:
    posting: dict[str, object]
    profile: dict[str, object]
    history: list[dict[str, object]]
    posting_sha256: str
    profile_sha256: str
    history_sha256: str

    def fingerprints(self) -> tuple[str, str, str]:
        return self.posting_sha256, self.profile_sha256, self.history_sha256


def _sha256(value: object) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=True
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _capture(connection: Connection, posting_id: str, *, lock: bool = False) -> _Inputs:
    if not isinstance(posting_id, str) or not posting_id.strip():
        raise ValueError("posting_id must be a nonblank string")
    if lock:
        connection.execute(
            "lock table public.profile, public.application_history in share mode"
        )
    query = (
        "select id::text, title, company, location, raw_jd from public.postings "
        "where id = %s for update"
        if lock else
        "select id::text, title, company, location, raw_jd from public.postings "
        "where id = %s"
    )
    row = connection.execute(query, (posting_id,)).fetchone()
    if row is None:
        raise LookupError("posting does not exist")
    posting = dict(zip(("id", "title", "company", "location", "raw_jd"), row))
    profile = {
        str(field): value
        for field, value in connection.execute(
            "select field, value from public.profile order by field"
        ).fetchall()
    }
    history = [
        dict(zip(("history_id", "company", "role", "application_date", "outcome"), item))
        for item in connection.execute(
            "select id::text, company, role, application_date, outcome "
            "from public.application_history order by application_date desc nulls last, "
            "recorded_at desc, id limit 20"
        ).fetchall()
    ]
    public_posting = projection.public_posting(posting)
    professional_profile = projection.profile_contract(profile)
    selected_history = projection.history_projection(history)
    return _Inputs(
        posting, profile, history, _sha256(public_posting),
        _sha256(professional_profile), _sha256(selected_history),
    )


def _labels(annotation: Mapping[str, object]) -> dict[str, object]:
    reasons = annotation["reasons"]
    if not isinstance(reasons, list):
        raise TypeError("validated reasons must be a list")
    by_factor = {reason["factor"]: reason for reason in reasons if isinstance(reason, dict)}
    seniority = by_factor["seniority_gap"]["assessment"]
    remote = by_factor["preferences"]["assessment"]
    if remote != "unknown":
        raise ValueError("withheld preferences must remain unknown")
    supported = " ".join(
        str(reason["detail"])
        for factor in ("product_role_match", "stack_domain_evidence")
        if (reason := by_factor[factor])["assessment"] in {"positive", "mixed"}
    )
    matches = [
        label for label, pattern in (
            ("fullstack", r"\bfull[ -]?stack\b"),
            ("frontend", r"\bfront[ -]?end\b"),
            ("ai", r"\b(?:AI|LLM|machine learning|artificial intelligence)\b"),
            ("voice", r"\b(?:voice|speech|audio)\b"),
        ) if re.search(pattern, supported, re.IGNORECASE)
    ]
    return {
        "role_type": matches[0] if len(matches) == 1 else None,
        "seniority_match": seniority,
        "remote_ok": remote,
        "red_flag_count": sum(
            reason.get("assessment") == "negative"
            for reason in reasons if isinstance(reason, dict)
        ),
    }


def _store(
    connection: Connection, captured: _Inputs, result: core.ScoringResult
) -> PersistOutcome:
    payload = json.loads(json.dumps(result.annotation, ensure_ascii=False, allow_nan=False))
    labels = _labels(payload)
    desired = (
        payload["fit_score"], payload["reasons"], labels, result.brain, result.model,
        SCORER_VERSION, *captured.fingerprints(), payload,
    )
    with connection.transaction():
        current_inputs = _capture(connection, str(captured.posting["id"]), lock=True)
        if current_inputs.fingerprints() != captured.fingerprints():
            return "stale"
        current = connection.execute(
            "select score, reasons, labels, brain, model, scorer_version, posting_sha256, "
            "profile_sha256, history_sha256, score_payload from public.posting_scores "
            "where posting_id = %s", (captured.posting["id"],),
        ).fetchone()
        if current == desired:
            return "unchanged"
        stored = connection.execute(
            "insert into public.posting_scores (posting_id, score, reasons, labels, brain, "
            "model, scorer_version, posting_sha256, profile_sha256, history_sha256, "
            "score_payload, scored_at) values "
            "(%s, %s, %s::jsonb, %s::jsonb, %s, %s, %s, %s, %s, %s, %s::jsonb, "
            "clock_timestamp()) on conflict (posting_id) do update set "
            "score=excluded.score, reasons=excluded.reasons, labels=excluded.labels, "
            "brain=excluded.brain, model=excluded.model, scorer_version=excluded.scorer_version, "
            "posting_sha256=excluded.posting_sha256, profile_sha256=excluded.profile_sha256, "
            "history_sha256=excluded.history_sha256, score_payload=excluded.score_payload, "
            "scored_at=excluded.scored_at returning posting_id",
            (
                captured.posting["id"], desired[0], json.dumps(desired[1]),
                json.dumps(desired[2]), *desired[3:9], json.dumps(desired[9]),
            ),
        ).fetchone()
        if stored is None:
            raise RuntimeError("score persistence returned no posting identity")
        return "stored"


def score_and_persist(
    connection: Connection, posting_id: str, *, brain_runner: core.BrainRunner = core.run_brain
) -> PersistOutcome:
    """Score one captured snapshot and persist only a current validated result."""

    captured = _capture(connection, posting_id)
    result = core.score_posting(
        captured.profile, captured.posting, captured.history, brain_runner=brain_runner
    )
    return "failed" if result is None else _store(connection, captured, result)


def list_scoring_candidates(
    connection: Connection, *, limit: int, posting_ids: Sequence[str] = ()
) -> list[str]:
    """Select extracted/no-score rows plus open rows after a profile change."""

    if type(limit) is not int or not 1 <= limit <= 1000:
        raise ValueError("limit must be between 1 and 1000")
    profile = {
        str(field): value for field, value in connection.execute(
            "select field, value from public.profile order by field"
        ).fetchall()
    }
    profile_sha256 = _sha256(projection.profile_contract(profile))
    requested = list(dict.fromkeys(posting_ids))
    rows = connection.execute(
        "select p.id::text from public.postings p join public.posting_extractions e "
        "on e.posting_id=p.id join public.posting_status st on st.posting_id=p.id "
        "left join public.posting_scores s on s.posting_id=p.id where (s.posting_id is null "
        "or (st.status in ('new','seen') and s.profile_sha256 is distinct from %s)) "
        "and (%s::uuid[] is null or p.id = any(%s::uuid[])) "
        "order by p.posted_at desc nulls last, p.id limit %s",
        (profile_sha256, requested or None, requested or None, limit),
    ).fetchall()
    return [str(row[0]) for row in rows]
