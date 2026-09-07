"""Semantic evidence validation for extracted public job facts."""

from __future__ import annotations

import re

from scraper.brain_contract import BrainValidationError


_REMOTE_WORD = r"\bremote(?:ly)?\b"
_REMOTE_AVAILABILITY = (
    r"(?:available|allowed|offered|permitted|possible|supported|an\s+option)"
)
_REMOTE_DENIAL_ACTION = r"(?:offer|allow|permit|support|provide|accommodate|approve)"
_REMOTE_CLAUSE_TEXT = r"(?:(?!\b(?:and|but|while|whereas|however)\b)[^,.!?;\n])"
_REMOTE_WORD_RE = re.compile(_REMOTE_WORD, re.IGNORECASE)
_REMOTE_ONSITE_RE = re.compile(
    r"\b(?:on[ -]?site|office[ -]based)\b",
    re.IGNORECASE,
)
_REMOTE_NEGATED_BEFORE_RE = re.compile(
    rf"\bnon[ -]?remote\b|"
    rf"\bno\s+(?:longer\s+)?(?:fully\s+)?{_REMOTE_WORD}|"
    rf"\bno\s+(?:option|possibility|opportunity)\b"
    rf"{_REMOTE_CLAUSE_TEXT}{{0,32}}{_REMOTE_WORD}|"
    rf"\b(?:never|without)\s+(?:an?\s+|any\s+)?{_REMOTE_WORD}|"
    rf"\b(?:cannot|can't|can not)\b{_REMOTE_CLAUSE_TEXT}{{0,32}}{_REMOTE_WORD}|"
    rf"\bnot(?!\s+only\b)\s+(?:currently\s+)?(?:an?\s+)?{_REMOTE_WORD}|"
    rf"\b(?:do|does|did|will|would)\s+not\s+{_REMOTE_DENIAL_ACTION}\b"
    rf"{_REMOTE_CLAUSE_TEXT}{{0,32}}{_REMOTE_WORD}|"
    rf"\b(?:don't|doesn't|didn't|won't|wouldn't)\s+{_REMOTE_DENIAL_ACTION}\b"
    rf"{_REMOTE_CLAUSE_TEXT}{{0,32}}{_REMOTE_WORD}",
    re.IGNORECASE,
)
_REMOTE_NEGATED_AFTER_RE = re.compile(
    rf"{_REMOTE_WORD}{_REMOTE_CLAUSE_TEXT}{{0,64}}\b(?:"
    r"(?:is|are|was|were|will|would|can|could)?\s*"
    r"(?:not(?!\s+only\b)|never|cannot|can't|won't|wouldn't|couldn't|"
    r"isn't|aren't|wasn't|weren't)"
    r"(?:\s+(?:currently|generally|yet))?\s+"
    rf"(?:be\s+)?{_REMOTE_AVAILABILITY}"
    r"|(?:is|are|was|were)?\s*(?:unavailable|prohibited|forbidden|disallowed)"
    rf"|no\s+longer\s+{_REMOTE_AVAILABILITY}"
    r")\b",
    re.IGNORECASE,
)


def _validate_quote(
    field: str,
    value: object,
    quote: object,
    raw_jd: str,
) -> None:
    if value is None:
        if quote is not None:
            raise BrainValidationError(f"unknown {field} cannot cite evidence")
        return
    if not isinstance(quote, str) or not quote.strip() or quote not in raw_jd:
        raise BrainValidationError(f"{field} evidence must be an exact nonblank quote")
    if isinstance(value, str) and (
        not value.strip() or not re.search(
            rf"(?<!\w){re.escape(value)}(?!\w)", quote, re.IGNORECASE
        )
    ):
        raise BrainValidationError(f"{field} value must occur in its evidence quote")


def _remote_quote_value(quote: str) -> bool | None:
    negative = _REMOTE_NEGATED_BEFORE_RE.search(
        quote
    ) or _REMOTE_NEGATED_AFTER_RE.search(quote)
    if negative:
        return False
    if _REMOTE_WORD_RE.search(quote):
        return True
    if _REMOTE_ONSITE_RE.search(quote):
        return False
    return None


def _remote_source_values(quote: str, raw_jd: str) -> set[bool | None]:
    values: set[bool | None] = set()
    offset = 0
    while (quote_start := raw_jd.find(quote, offset)) >= 0:
        quote_end = quote_start + len(quote)
        semantic_end = quote_start + len(quote.rstrip(" \t.!?;\n"))
        clause_start = max(
            raw_jd.rfind(boundary, 0, quote_start)
            for boundary in ".!?;\n"
        )
        following_boundaries = [
            position
            for boundary in ".!?;\n"
            if (position := raw_jd.find(boundary, semantic_end)) >= 0
        ]
        clause_end = min(following_boundaries, default=len(raw_jd))
        values.add(_remote_quote_value(raw_jd[clause_start + 1:clause_end]))
        offset = quote_end
    return values


def validate_facts(facts: dict[str, object], raw_jd: str) -> None:
    """Reject extracted facts that are not supported by their source quotes."""

    for field in ("location", "remote", "seniority", "salary"):
        fact = facts[field]
        assert isinstance(fact, dict)
        _validate_quote(field, fact["value"], fact["evidence_quote"], raw_jd)
    remote = facts["remote"]
    assert isinstance(remote, dict)
    remote_value = remote["value"]
    remote_quote = remote["evidence_quote"]
    if remote_value is not None:
        assert isinstance(remote_quote, str)
        quote_value = _remote_quote_value(remote_quote)
        source_values = _remote_source_values(remote_quote, raw_jd)
        if quote_value is not remote_value or source_values != {remote_value}:
            raise BrainValidationError("remote value conflicts with its evidence quote")

    stack = facts["stack"]
    assert isinstance(stack, list)
    seen: set[str] = set()
    for fact in stack:
        assert isinstance(fact, dict)
        value = fact["value"]
        quote = fact["evidence_quote"]
        _validate_quote("stack", value, quote, raw_jd)
        assert isinstance(value, str)
        normalized = value.strip().casefold()
        if normalized in seen:
            raise BrainValidationError("stack facts must be unique")
        seen.add(normalized)
