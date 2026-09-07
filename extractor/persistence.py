"""Atomic persistence for last-good structured extraction results."""

from __future__ import annotations

from collections.abc import Mapping
from contextlib import AbstractContextManager
import hashlib
import json
from typing import Literal, Protocol

from extractor.payload import build_payload, fingerprint, require_sha256, require_text


class Result(Protocol):
    def fetchone(self) -> tuple[object, ...] | None: ...


class Connection(Protocol):
    def execute(self, query: str, params: tuple[object, ...] = ()) -> Result: ...
    def transaction(self) -> AbstractContextManager[object]: ...


PersistOutcome = Literal["stored", "unchanged", "stale"]


def has_current_extraction(
    connection: Connection,
    posting_id: str,
    raw_jd: str,
    *,
    brain: str,
    model: str,
    extractor_version: str,
    schema_sha256: str,
) -> bool:
    """Return true only for the exact current JD and observed processor identity."""

    posting_id = require_text(posting_id, "posting_id")
    if not isinstance(raw_jd, str) or not raw_jd.strip():
        raise ValueError("raw JD must be a nonblank string")
    brain = require_text(brain, "brain")
    model = require_text(model, "model")
    version = require_text(extractor_version, "extractor_version")
    schema_sha256 = require_sha256(schema_sha256, "schema_sha256")
    jd_sha256 = hashlib.sha256(raw_jd.encode()).hexdigest()
    result_fingerprint = fingerprint(brain, model, version, schema_sha256, jd_sha256)
    row = connection.execute(
        "select exists (select 1 from public.postings p join public.posting_extractions e "
        "on e.posting_id = p.id where p.id = %s and p.raw_jd = %s and e.brain = %s "
        "and e.model = %s and e.extractor_version = %s and e.schema_sha256 = %s "
        "and e.jd_sha256 = %s and e.fingerprint = %s)",
        (
            posting_id, raw_jd, brain, model, version, schema_sha256, jd_sha256,
            result_fingerprint,
        ),
    ).fetchone()
    return row == (True,)


def persist_extraction(
    connection: Connection,
    posting_id: str,
    captured_raw_jd: str,
    extraction: Mapping[str, object],
) -> PersistOutcome:
    """Store one valid last-good result unless its captured JD became stale."""

    posting_id = require_text(posting_id, "posting_id")
    if not isinstance(captured_raw_jd, str) or not captured_raw_jd.strip():
        raise ValueError("captured raw JD must be a nonblank string")
    payload = build_payload(extraction, captured_raw_jd)
    with connection.transaction():
        posting = connection.execute(
            "select raw_jd from public.postings where id = %s for update",
            (posting_id,),
        ).fetchone()
        if posting is None:
            raise LookupError("posting does not exist")
        if posting[0] != captured_raw_jd:
            return "stale"
        current = connection.execute(
            "select brain, model, extractor_version, schema_sha256, jd_sha256, "
            "fingerprint, facts from public.posting_extractions where posting_id = %s",
            (posting_id,),
        ).fetchone()
        if current == payload.metadata():
            return "unchanged"
        updated = connection.execute(
            "update public.postings set location = coalesce(%s, location), "
            "remote = coalesce(%s, remote), seniority = coalesce(%s, seniority), "
            "stack = case when cardinality(%s::text[]) > 0 then %s::text[] else stack end, "
            "salary = coalesce(%s, salary) where id = %s and raw_jd = %s returning id",
            (
                payload.facts["location"]["value"], payload.facts["remote"]["value"],
                payload.facts["seniority"]["value"],
                [fact["value"] for fact in payload.facts["stack"]],
                [fact["value"] for fact in payload.facts["stack"]],
                payload.facts["salary"]["value"], posting_id, captured_raw_jd,
            ),
        ).fetchone()
        if updated is None:
            return "stale"
        stored = connection.execute(
            "insert into public.posting_extractions "
            "(posting_id, brain, model, extractor_version, schema_sha256, jd_sha256, "
            "fingerprint, facts, extracted_at) values "
            "(%s, %s, %s, %s, %s, %s, %s, %s::jsonb, clock_timestamp()) "
            "on conflict (posting_id) do update set brain = excluded.brain, "
            "model = excluded.model, extractor_version = excluded.extractor_version, "
            "schema_sha256 = excluded.schema_sha256, jd_sha256 = excluded.jd_sha256, "
            "fingerprint = excluded.fingerprint, facts = excluded.facts, "
            "extracted_at = excluded.extracted_at returning posting_id",
            (posting_id, *payload.metadata()[:-1], json.dumps(payload.facts, ensure_ascii=False)),
        ).fetchone()
        if stored is None:
            raise RuntimeError("extraction persistence returned no posting identity")
        return "stored"
