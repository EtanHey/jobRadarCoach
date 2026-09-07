"""Validate and project captured scoring inputs without provider access."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
import re

from scraper.annotate import MCP_EVIDENCE_IDS
from scraper.database import annotation_profile


MIN_JD_CHARS = 200
MAX_HISTORY_ENTRIES = 20
MAX_HISTORY_TEXT_CHARS = 500
DEPTH_MODES = frozenset({"hands-on", "directed-AI", "studied-with-AI"})


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a nonblank string")
    return value.strip()


def _history_text(value: object, field: str) -> str:
    text = _text(value, field)
    if len(text) > MAX_HISTORY_TEXT_CHARS:
        raise ValueError(f"{field} is too long")
    return text


def _string_list(
    value: object, field: str, *, allow_empty: bool = False
) -> list[str]:
    if not isinstance(value, list) or (not value and not allow_empty):
        raise ValueError(f"{field} must be a list")
    normalized = [_text(item, field) for item in value]
    if len(normalized) != len(set(normalized)):
        raise ValueError(f"{field} contains duplicates")
    return normalized


def _validate_candidate(candidate: object) -> None:
    if not isinstance(candidate, dict):
        raise ValueError("candidate must be an object")
    _text(candidate.get("positioning"), "candidate.positioning")
    tenure = candidate.get("tenure_years")
    if type(tenure) not in {int, float} or not 0 <= float(tenure) <= 100:
        raise ValueError("candidate.tenure_years is invalid")
    _string_list(candidate.get("fit_terms"), "candidate.fit_terms")
    depth = candidate.get("professional_depth", {})
    if not isinstance(depth, dict):
        raise ValueError("candidate.professional_depth must be an object")
    for technology, modes in depth.items():
        _text(technology, "professional depth technology")
        if set(_string_list(modes, f"professional depth {technology}")) - DEPTH_MODES:
            raise ValueError("professional depth contains an unknown mode")


def _validate_signals(signals: object) -> None:
    if not isinstance(signals, list):
        raise ValueError("fit_signals must be a list")
    seen: set[str] = set()
    for signal in signals:
        if not isinstance(signal, dict):
            raise ValueError("fit signal must be an object")
        evidence_id = _text(signal.get("evidence_id"), "fit signal evidence_id")
        if evidence_id in seen or not re.fullmatch(
            r"[a-z0-9][a-z0-9:-]*", evidence_id
        ):
            raise ValueError("fit signal evidence_id is invalid")
        tags = _string_list(signal.get("tags"), f"fit signal {evidence_id}.tags")
        _text(signal.get("claim"), f"fit signal {evidence_id}.claim")
        ownership = signal.get("ownership")
        if not isinstance(ownership, dict):
            raise ValueError("fit signal ownership must be an object")
        _text(ownership.get("verified_scope"), "ownership.verified_scope")
        _string_list(
            ownership.get("exclusions"), "ownership.exclusions", allow_empty=True
        )
        if signal.get("status") != "verified" or (
            "mcp" in tags and evidence_id not in MCP_EVIDENCE_IDS
        ):
            raise ValueError("fit signal is not verified professional evidence")
        seen.add(evidence_id)


def _validate_constraints(constraints: object) -> None:
    if not isinstance(constraints, dict):
        raise ValueError("local constraints must be an object")
    _string_list(
        constraints.get("global_never_claims"),
        "global_never_claims",
        allow_empty=True,
    )
    scoped = constraints.get("evidence_scoped_prohibitions")
    if not isinstance(scoped, dict):
        raise ValueError("evidence_scoped_prohibitions must be an object")
    for evidence_id, prohibitions in scoped.items():
        _text(evidence_id, "scoped evidence_id")
        _string_list(prohibitions, "scoped prohibitions", allow_empty=True)


def profile_contract(snapshot: Mapping[str, object]) -> dict[str, object]:
    if not isinstance(snapshot, Mapping) or snapshot.get("contract_version") != 1:
        raise ValueError("captured DB profile contract is invalid")
    profile = annotation_profile(dict(snapshot))
    _validate_candidate(profile["candidate"])
    _validate_signals(profile.get("fit_signals"))
    _validate_constraints(profile.get("constraints"))
    return profile


def public_posting(posting: Mapping[str, object]) -> dict[str, object]:
    if not isinstance(posting, Mapping):
        raise ValueError("posting must be an object")
    public = {
        "id": _text(posting.get("id"), "posting.id"),
        "title": _text(posting.get("title"), "posting.title"),
        "company": _text(posting.get("company"), "posting.company"),
        "location": str(posting.get("location") or "").strip(),
        "jd_text": _text(posting.get("raw_jd"), "posting.raw_jd"),
    }
    if len(public["jd_text"]) < MIN_JD_CHARS:
        raise ValueError("posting.raw_jd is not substantive")
    for field in ("human_verdict", "verdict"):
        if field in posting:
            public[field] = posting[field]
    return public


def history_projection(
    history: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    if isinstance(history, (str, bytes)) or not isinstance(history, Sequence):
        raise ValueError("application history must be a sequence")
    if len(history) > MAX_HISTORY_ENTRIES:
        raise ValueError("application history exceeds its entry limit")
    projected: list[dict[str, object]] = []
    seen: set[str] = set()
    for row in history:
        if not isinstance(row, Mapping):
            raise ValueError("application history row must be an object")
        raw_id = row.get("history_id", row.get("id"))
        raw_evidence_id = "" if raw_id is None else str(raw_id).strip()
        evidence_id = f"application-history:{raw_evidence_id}"
        if not raw_evidence_id or len(raw_evidence_id) > 128 or evidence_id in seen:
            raise ValueError("application history id is invalid")
        entry: dict[str, object] = {
            "evidence_id": evidence_id,
            "company": _history_text(
                row.get("company"), "application history company"
            ),
        }
        for field in ("role", "application_date", "outcome"):
            value = row.get(field)
            if value is None:
                entry[field] = None
            elif field == "application_date" and isinstance(value, date):
                entry[field] = value.isoformat()
            else:
                entry[field] = _history_text(value, f"application history {field}")
        seen.add(evidence_id)
        projected.append(entry)
    return projected
