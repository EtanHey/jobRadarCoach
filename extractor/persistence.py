"""Atomic persistence for last-good structured extraction results."""

from __future__ import annotations

from scraper.annotate import location_mode, posting_mode
from scraper.employer_identity import VERSION, resolve_employer
from scraper.deadlines import SOURCE as DEADLINE_SOURCE, extract_deadline

from collections.abc import Mapping
from contextlib import AbstractContextManager
import hashlib
import json
from typing import Literal, Protocol

from extractor.payload import build_payload, fingerprint, require_sha256, require_text
from extractor.evidence import attendance_evidence


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
        "and e.jd_sha256 = %s and e.fingerprint = %s "
        "and e.facts->'employer_identity'->>'resolver_version' = %s "
        "and e.facts->'employer_identity'->>'publisher' = p.company)",
        (
            posting_id, raw_jd, brain, model, version, schema_sha256, jd_sha256,
            result_fingerprint, VERSION,
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
            "select raw_jd, company, source from public.postings where id = %s for update",
            (posting_id,),
        ).fetchone()
        if posting is None:
            raise LookupError("posting does not exist")
        if posting[0] != captured_raw_jd:
            return "stale"
        deadline = extract_deadline(captured_raw_jd)
        encoded_deadline = json.dumps(deadline, ensure_ascii=False)
        # Separate from page/list verdicts. Refresh even for an unchanged LLM
        # receipt; only clear a removed deadline previously owned by this parser.
        connection.execute(
            "update public.postings set liveness = liveness || %s::jsonb "
            "where id = %s and raw_jd = %s "
            "and (%s or liveness->>'application_deadline_source' = %s) "
            "and not liveness @> %s::jsonb",
            (encoded_deadline, posting_id, captured_raw_jd,
             deadline["application_deadline_evidence_quote"] is not None,
             DEADLINE_SOURCE, encoded_deadline),
        )
        payload.facts["employer_identity"] = resolve_employer(
            str(posting[1]), captured_raw_jd, str(posting[2]),
        )
        current = connection.execute(
            "select brain, model, extractor_version, schema_sha256, jd_sha256, "
            "fingerprint, facts from public.posting_extractions where posting_id = %s",
            (posting_id,),
        ).fetchone()
        if current == payload.metadata():
            return "unchanged"
        mode, mode_source = posting_mode({
            "work_mode": location_mode(payload.facts["location"]["value"]),
            "location": payload.facts["location"]["value"],
            "remote": payload.facts["remote"]["value"],
        })
        attendance = attendance_evidence(captured_raw_jd)
        attendance_mode = attendance[0] if attendance else None
        updated = connection.execute(
            "update public.postings set location = coalesce(%s, location), "
            "remote = case when %s::text is not null then case when %s = 'on-site' then false else null end else case (case when work_mode_source in ('structured', 'location') then work_mode "
            "else coalesce(%s, work_mode) end) when 'remote' then true when 'on-site' then false "
            "when 'hybrid' then null else coalesce(%s, remote) end end, "
            "work_mode = case when %s::text is not null then nullif(%s, 'unknown') when work_mode_source in ('structured', 'location') then work_mode "
            "else coalesce(%s, work_mode) end, "
            "work_mode_source = case when %s::text is not null then case when %s = 'unknown' then null else 'extracted' end when work_mode_source in ('structured', 'location') then work_mode_source "
            "else coalesce(%s, work_mode_source) end, seniority = coalesce(%s, seniority), "
            "stack = case when cardinality(%s::text[]) > 0 then %s::text[] else stack end, "
            "salary = coalesce(%s, case when lower(salary) = lower(%s) then null else salary end) "
            "where id = %s and raw_jd = %s returning id",
            (
                payload.facts["location"]["value"], attendance_mode, attendance_mode, mode,
                payload.facts["remote"]["value"], attendance_mode, attendance_mode, mode,
                attendance_mode, attendance_mode, "extracted" if mode_source else None,
                payload.facts["seniority"]["value"],
                [fact["value"] for fact in payload.facts["stack"]],
                [fact["value"] for fact in payload.facts["stack"]],
                payload.facts["salary"]["value"], payload.facts.get("salary_remark"),
                posting_id, captured_raw_jd,
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
