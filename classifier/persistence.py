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
from scraper.relevance import refresh_gate, SELECTION_GUARD, VERSION

SCORER_VERSION = "1.4"
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
        "select id::text, title, company, location, raw_jd, remote, "
        "to_jsonb(postings)->>'work_mode' from public.postings where id = %s"
        + (" for update" if lock else "")
    )
    row = connection.execute(query, (posting_id,)).fetchone()
    if row is None:
        raise LookupError("posting does not exist")
    posting = dict(zip(("id", "title", "company", "location", "raw_jd", "remote", "work_mode"), row))
    extraction = connection.execute(
        "select facts from public.posting_extractions where posting_id = %s"
        + (" for update" if lock else ""), (posting_id,),
    ).fetchone()
    posting["posting_extractions"] = None if extraction is None else {"facts": extraction[0]}
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
        posting, profile, history, _sha256({
            "public_posting": public_posting,
            "work_mode": posting["work_mode"],
            "remote": posting["remote"],
            "posting_extractions": posting["posting_extractions"],
        }),
        _sha256(professional_profile), _sha256(selected_history),
    )


def _ai_software_occupation(title: str, specialty: str) -> bool:
    """Resolve a primary software head without discarding its attached AI frame."""
    occupation = re.sub(specialty, "AI", title, flags=re.IGNORECASE)
    occupation = re.sub(r"\bAI-native\b", "AI native", occupation, flags=re.IGNORECASE)
    # These frames describe the worker's use of assistants, not an AI product.
    # Ambiguous marketing terms need JD corroboration outside this title-only rule.
    if re.search(
        r"\bAI[ -]+(?:builder|fluent)\b"
        r"|\bAI[ -]+(?:driven|powered|assisted)\s+"
        r"(?:development|coding|(?:software|SW)\s+(?:engineer|developer))\b"
        r"|\b(?:using|use of|assisted by)\s+AI\b",
        occupation, re.IGNORECASE,
    ):
        return False

    rank = (
        r"(?:(?:senior|sr\.?|junior|jr\.?|staff|principal|lead|applied|founding|"
        r"founder style|customer|GTM|C\+\+|C\#|Python|Java|Golang|Angular)\s+)*"
    )
    domain = (
        r"(?:software development|software|SW|back[ -]?end|front[ -]?end|"
        r"full[ -]?stack|AI|agents?|platform|systems?|data|applications?|web|"
        r"solutions?|algorithms?|computer vision|cybersecurity|security|DevOps|"
        r"forward deployed|developer technology|network simulation|native)"
    )
    domains = rf"{domain}(?:(?:\s+|\s*[&/]\s*|\s+and\s+){domain})*"
    # A leading specialisation may precede the occupation: AI Security - SWE.
    # It is itself a closed domain phrase, never another occupation (e.g. Sales).
    frame = rf"(?:{domains}\s+[-–—]\s+)?"
    match = re.match(
        rf"^{rank}{frame}{rank}(?:manager\s*,\s*)?"
        rf"(?P<domains>{domains})\s+"
        rf"(?P<head>engineering\s+manager|engineer|developer|architect|researcher|engineering)\b"
        rf"(?:\s+(?:I|II|III|IV|V))?"
        rf"(?=$|\s*[,(/:–—-]|\s+(?:with|for|in|and)\b)",
        occupation.strip(), re.IGNORECASE,
    )
    if match is None:
        return False
    fields = match.group("domains")
    head = match.group("head").lower()
    if head in {"researcher", "engineering", "engineering manager"}:
        return bool(re.search(r"\b(?:AI|software|SW)\b", fields, re.IGNORECASE))
    # Network simulation and security can modify software/AI occupations, but
    # cannot turn generic network/security operations into software by themselves.
    return bool(re.search(
        r"\b(?:AI|software|SW|back[ -]?end|front[ -]?end|full[ -]?stack|"
        r"platform|systems?|data|applications?|web|solutions?|algorithms?|"
        r"DevOps|forward deployed|developer technology)\b", fields, re.IGNORECASE,
    ))


def _role_type(title: object) -> str | None:
    """Title-only identity; unknown occupational modifiers default to abstention.

    Frontend/fullstack/AI require a software occupation head, directly modified
    by the specialty and optional closed software-domain modifiers. AI accepts
    attached team/product/specialisation frames of an anchored software head.
    Hardware domains veto every specialty. Voice specializes AI; AI specializes
    frontend/fullstack. Other multiple matches are ambiguous.
    """
    if not isinstance(title, str) or re.search(
        r"\b(?:hardware|chip|RTL|power|silicon|analog|ASIC|FPGA)\b", title, re.IGNORECASE
    ):
        return None
    patterns = {
        "fullstack": r"\bfull[ -]?stack\b",
        "frontend": r"\bfront[ -]?end\b",
        "ai": r"\b(?:AI|ML|LLM|Gen\s?AI|generative AI|machine learning|artificial intelligence|agentic|agents)\b",
        "voice": r"\b(?:voice|speech|audio)\b",
    }
    matches = {label for label, pattern in patterns.items() if re.search(pattern, title, re.IGNORECASE)}
    if matches == {"voice", "ai"}:
        return "voice"
    if "ai" in matches:
        if "voice" in matches:
            return None
        return "ai" if _ai_software_occupation(title, patterns["ai"]) else None
    if len(matches) != 1:
        return None
    label = matches.pop()
    if label in {"frontend", "fullstack"}:
        specialty = patterns[label]
        head = r"(?:developer|engineer|architect)\b"
        modifiers = r"(?:(?:software|web|applications?)\s+)*"
        direct = rf"{specialty}\s+{modifiers}{head}"
        # Accept inverted titles such as "Software Engineer II - Front-End".
        inverted = rf"\bsoftware\s+{head}(?:\s+(?:I|II|III|IV))?\s*[-,(/:]\s*{specialty}"
        if not re.search(rf"(?:{direct}|{inverted})", title, re.IGNORECASE):
            return None
    return label


def _labels(
    annotation: Mapping[str, object], posting: Mapping[str, object]
) -> dict[str, object]:
    reasons = annotation["reasons"]
    if not isinstance(reasons, list):
        raise TypeError("validated reasons must be a list")
    by_factor = {reason["factor"]: reason for reason in reasons if isinstance(reason, dict)}
    seniority = by_factor["seniority_gap"]["assessment"]
    remote = by_factor["preferences"]["assessment"]
    if remote != "unknown":
        raise ValueError("withheld preferences must remain unknown")
    # The advertised title is the role's identity frame. Comparison reasons,
    # company names and incidental JD technology mentions are not role titles.
    return {
        "role_type": _role_type(posting.get("title")),
        "seniority_match": seniority,
        "remote_ok": remote,
        "red_flag_count": sum(
            reason.get("assessment") == "negative"
            for reason in reasons if isinstance(reason, dict)
        ),
    }


def _ack_score_request(connection: Connection, posting_id: object) -> None:
    connection.execute(
        "update public.postings set relevance_gate=relevance_gate-'score_requested' "
        "where id=%s and relevance_gate->>'score_requested'='true'",
        (posting_id,),
    )


def _store(
    connection: Connection, captured: _Inputs, result: core.ScoringResult
) -> PersistOutcome:
    payload = json.loads(json.dumps(result.annotation, ensure_ascii=False, allow_nan=False))
    labels = _labels(payload, captured.posting)
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
            _ack_score_request(connection, captured.posting["id"])
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
        _ack_score_request(connection, captured.posting["id"])
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
    connection: Connection, *, limit: int, posting_ids: Sequence[str] = (),
    claimable_stage: str | None = None,
) -> list[str]:
    """Select substantive raw JDs without scores, or open rows after a profile change."""

    if type(limit) is not int or not 1 <= limit <= 1000:
        raise ValueError("limit must be between 1 and 1000")
    profile = {
        str(field): value for field, value in connection.execute(
            "select field, value from public.profile order by field"
        ).fetchall()
    }
    profile_sha256 = _sha256(projection.profile_contract(profile))
    requested = list(dict.fromkeys(posting_ids))
    if claimable_stage not in (None, "score"):
        raise ValueError("claimable stage must be score")
    refresh_gate(connection, posting_ids=requested)
    lease_filter = (
        "and not exists (select 1 from public.local_analysis_leases l "
        "where l.stage = %s and l.posting_id = p.id and "
        "(l.lease_expires_at > clock_timestamp() or l.next_attempt_at > clock_timestamp())) "
        if claimable_stage else ""
    )
    rows = connection.execute(
        "select p.id::text from public.postings p "
        "join public.posting_status st on st.posting_id=p.id "
        "left join public.posting_scores s on s.posting_id=p.id "
        "where p.liveness->'alive' is distinct from 'false'::jsonb "
        "and p.raw_jd is not null and char_length(regexp_replace(p.raw_jd, "
        "'(^[[:space:]]+|[[:space:]]+$)', '', 'g')) >= %s "
        "and (s.posting_id is null "
        "or (st.status in ('new','seen') and s.profile_sha256 is distinct from %s) "
        "or p.relevance_gate->>'score_requested'='true') "
        "and (%s::uuid[] is null or p.id = any(%s::uuid[])) "
        + SELECTION_GUARD + lease_filter
        + "order by (s.posting_id is null) desc, "
        "coalesce(p.posted_at, p.first_seen_at) desc, p.id limit %s",
        (projection.MIN_JD_CHARS, profile_sha256, requested or None, requested or None, VERSION)
        + ((claimable_stage,) if claimable_stage else ()) + (limit,),
    ).fetchall()
    return [str(row[0]) for row in rows]
