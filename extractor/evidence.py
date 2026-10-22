"""Semantic evidence validation for extracted public job facts."""

from __future__ import annotations

import re

from extractor.quotes import ExtractionValidationError, validate_quote
from extractor.salary import normalize_salary
from scraper.seniority import apply_title_seniority

_REMOTE_WORD = r"\bremote(?:ly)?\b"
_REMOTE_AVAILABILITY = (
    r"(?:available|allowed|offered|permitted|possible|supported|an\s+option)"
)
_REMOTE_DENIAL_ACTION = r"(?:offer|allow|permit|support|provide|accommodate|approve)"
_REMOTE_CLAUSE_TEXT = r"(?:(?!\b(?:and|but|while|whereas|however)\b)[^,.!?;\n])"
_REMOTE_WORD_RE = re.compile(_REMOTE_WORD, re.IGNORECASE)
_REMOTE_ONSITE_RE = re.compile(
    r"\b(?:on[ _-]?site|office[ -]based)\b",
    re.IGNORECASE,
)
_NON_ROLE_REMOTE_RE = re.compile(
    rf"\b(?:company|organization|business|team|workforce|staff|employees?)\b"
    rf"[^,.!?;\n]{{0,48}}\b(?:is|are|works?|operates?|collaborates?)\b"
    rf"[^,.!?;\n]{{0,32}}{_REMOTE_WORD}|"
    rf"{_REMOTE_WORD}[^,.!?;\n]{{0,24}}"
    r"\b(?:company|organization|business|team|workforce)\b|"
    rf"\b(?:benefits?|perks?)\b[^,.!?;\n]{{0,48}}{_REMOTE_WORD}",
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


def _remote_quote_value(quote: str) -> bool | None:
    if _NON_ROLE_REMOTE_RE.search(quote):
        return None
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


def derive_remote_fact(evidence_quote: object, raw_jd: str) -> dict[str, object]:
    """Construct remote value only when its exact source evidence is unambiguous."""

    if evidence_quote is None:
        return {"value": None, "evidence_quote": None}
    if (
        not isinstance(evidence_quote, str)
        or not evidence_quote.strip()
        or evidence_quote not in raw_jd
    ):
        # Preserve invalid evidence so the standard quote validator rejects it.
        return {"value": None, "evidence_quote": evidence_quote}
    quote_value = _remote_quote_value(evidence_quote)
    source_values = _remote_source_values(evidence_quote, raw_jd)
    if quote_value is not None and source_values == {quote_value}:
        return {"value": quote_value, "evidence_quote": evidence_quote}
    return {"value": None, "evidence_quote": None}


_NON_ROLE_LOCATION_RE = re.compile(
    r"\b(?:headquarters|headquartered)\b|"
    r"\bהמטה\b|"
    r"\boffices\s+(?:are\s+)?(?:located\s+)?in\b|"
    r"\b(?:within|across)\s+the\s+\w+\s+market\b|"
    r"\b(?:startup|company)\s+(?:is\s+)?based\s+in\b",
    re.IGNORECASE,
)


def _validate_location_context(fact: dict[str, object], raw_jd: str) -> None:
    if fact["value"] is None:
        return
    quote = fact["evidence_quote"]
    assert isinstance(quote, str)
    offset = 0
    while (start := raw_jd.find(quote, offset)) >= 0:
        before = max(raw_jd.rfind(boundary, 0, start) for boundary in ".!?;\n")
        after = [position for boundary in ".!?;\n"
                 if (position := raw_jd.find(boundary, start + len(quote))) >= 0]
        context = raw_jd[before + 1:min(after, default=len(raw_jd))]
        if _NON_ROLE_LOCATION_RE.search(context):
            raise ExtractionValidationError(
                "company geography does not establish job location",
                category="location_context",
                field="location",
            )
        offset = start + len(quote)


def validate_facts(facts: dict[str, object], raw_jd: str, posting_title: object = None) -> None:
    """Reject extracted facts that are not supported by their source quotes."""

    normalize_salary(facts, raw_jd)
    explicit = apply_title_seniority(facts, posting_title)
    for field in ("location", "remote", "seniority"):
        fact = facts[field]
        assert isinstance(fact, dict)
        source = posting_title if field == "seniority" and explicit is not None else raw_jd
        validate_quote(field, fact["value"], fact["evidence_quote"], source)
    _validate_location_context(facts["location"], raw_jd)
    remote = facts["remote"]
    assert isinstance(remote, dict)
    remote_value = remote["value"]
    remote_quote = remote["evidence_quote"]
    if remote_value is not None:
        assert isinstance(remote_quote, str)
        quote_value = _remote_quote_value(remote_quote)
        source_values = _remote_source_values(remote_quote, raw_jd)
        if quote_value is not remote_value or source_values != {remote_value}:
            raise ExtractionValidationError(
                "remote value conflicts with its evidence quote",
                category="remote_consistency",
                field="remote",
            )

    stack = facts["stack"]
    assert isinstance(stack, list)
    seen: set[str] = set()
    for fact in stack:
        assert isinstance(fact, dict)
        value = fact["value"]
        quote = fact["evidence_quote"]
        validate_quote("stack", value, quote, raw_jd)
        assert isinstance(value, str)
        normalized = value.strip().casefold()
        if normalized in seen:
            raise ExtractionValidationError(
                "stack facts must be unique",
                category="stack_uniqueness",
                field="stack",
            )
        seen.add(normalized)
