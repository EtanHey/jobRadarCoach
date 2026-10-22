"""Semantic evidence validation for extracted public job facts."""

from __future__ import annotations

import re

from extractor.quotes import ExtractionValidationError, validate_quote
from extractor.salary import normalize_salary

_DAYS = r"(?:[1-4]|one|two|three|four)\s+days?"
_WEEK = r"(?:(?:a|per|each)\s+week|weekly)"
_OFFICE = r"(?:in|at|from)\s+(?:(?:the|our)\s+)?office"
_HYBRID_POLICY_RE = re.compile(
    rf"\b(?:{_DAYS}\s+(?:{_WEEK}\s+)?{_OFFICE}|"
    rf"{_OFFICE}\s+(?:for\s+)?{_DAYS}\s+{_WEEK})\b|"
    r"\b(?:[1-4]\s+ימים|יומיים)\s+(?:בשבוע\s+)?במשרד\b|"
    r"\bhybrid[ -](?:work(?:ing)?|schedule|arrangement|policy)\b|"
    r"\b(?:work(?:ing)?\s+(?:in|on)|work[ -]model\s*:)\s+(?:a\s+)?hybrid\b|"
    r"\b(?:this|the)\s+(?:is\s+an?\s+)?hybrid\s+(?:role|position)\b|"
    r"\b(?:role|position|work(?:place)?|work[ -]model)\s*(?::|is|will\s+be)\s*hybrid\b|"
    r"\b(?:location|מיקום)\s*:[^.!?;\n]*\b(?:hybrid|היברידי(?:ת)?)\b|"
    r"\b(?:עבודה|משרה|מודל)\s+היברידי(?:ת)?\b|"
    r"^[ \t*#-]*(?:hybrid(?:\s+model)?|היברידי(?:ת)?)[ \t*.:]*$",
    re.IGNORECASE | re.MULTILINE,
)
_OPTIONAL_ATTENDANCE_RE = re.compile(
    r"\b(?:not(?!\s+only\b)|no|without)\s+(?:\w+[ -]){0,3}$|"
    r"\b(?:optional(?:ly)?|not\s+required|do\s+not\s+require)\b|"
    r"\b(?:may|can)\s+(?:choose\s+to\s+)?(?:work|visit|come|attend)\b|"
    r"(?:לא\s+נדרש|ללא\s+חובת)", re.IGNORECASE,
)


_FULL_OFFICE_RE = re.compile(
    rf"\b(?:(?:5|five)\s+days\s+{_WEEK}\s+{_OFFICE}|"
    rf"{_OFFICE}\s+(?:for\s+)?(?:5|five)\s+days\s+{_WEEK}|"
    rf"5/5\s+days\s+{_OFFICE}|(?:5|five)\s+office\s+days|"
    rf"full[ -]time\s+{_OFFICE}|fully\s+in[ -]person)\b|"
    r"\b5\s+ימים\s+בשבוע\s+במשרד\b", re.IGNORECASE,
)
_OTHER_ROLE_SCOPE_RE = re.compile(
    r"\b(?:some|other|certain)\s+(?:\w+[ -]){0,4}(?:roles?|positions?|teams?)\b",
    re.IGNORECASE,
)
_CONTRAST_RE = re.compile(r"\b(?:but|however|whereas)\b", re.IGNORECASE)


def attendance_evidence(raw_jd: str) -> tuple[str, str] | None:
    """Resolve role-scoped attendance; a full office week is not hybrid."""
    for mode, pattern in (("on-site", _FULL_OFFICE_RE), ("hybrid", _HYBRID_POLICY_RE)):
        for match in pattern.finditer(raw_jd):
            start = max(raw_jd.rfind(boundary, 0, match.start()) for boundary in ".!?;\n") + 1
            ends = [position for boundary in ".!?;\n"
                    if (position := raw_jd.find(boundary, match.end())) >= 0]
            end = min(ends, default=len(raw_jd))
            before = _CONTRAST_RE.split(raw_jd[start:match.start()])[-1]
            after = _CONTRAST_RE.split(raw_jd[match.end():end])[0]
            clause = before + match.group() + after
            if _OTHER_ROLE_SCOPE_RE.search(clause):
                continue
            if _OPTIONAL_ATTENDANCE_RE.search(before) or re.match(
                r"\s+(?:(?:is|are)\s+)?(?:optional|not\s+required)\b", after, re.I,
            ):
                continue
            return mode, clause.strip()
    return None


def hybrid_evidence(raw_jd: str) -> str | None:
    """Compatibility projection for callers interested only in hybrid evidence."""
    evidence = attendance_evidence(raw_jd)
    return evidence[1] if evidence and evidence[0] == "hybrid" else None


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
    attendance = attendance_evidence(raw_jd)
    if attendance is not None:
        return {False if attendance[0] == "on-site" else None}
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


def validate_facts(facts: dict[str, object], raw_jd: str) -> None:
    """Reject extracted facts that are not supported by their source quotes."""

    normalize_salary(facts, raw_jd)
    for field in ("location", "remote", "seniority"):
        fact = facts[field]
        assert isinstance(fact, dict)
        validate_quote(field, fact["value"], fact["evidence_quote"], raw_jd)
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
