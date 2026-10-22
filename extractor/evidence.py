"""Semantic evidence validation for extracted public job facts."""

from __future__ import annotations

import re
from typing import Literal

from scraper.brain_contract import BrainValidationError

ExtractionFailureCategory = Literal[
    "evidence_quote",
    "location_context",
    "remote_consistency",
    "stack_uniqueness",
]
ExtractionFailureField = Literal["location", "remote", "seniority", "salary", "stack"]
_FAILURE_CATEGORIES = frozenset(
    {"evidence_quote", "location_context", "remote_consistency", "stack_uniqueness"}
)
_FAILURE_FIELDS = frozenset({"location", "remote", "seniority", "salary", "stack"})


class ExtractionValidationError(BrainValidationError):
    """Evidence rejection carrying only bounded diagnostic metadata."""

    def __init__(
        self,
        message: str,
        *,
        category: ExtractionFailureCategory,
        field: ExtractionFailureField,
    ) -> None:
        if category not in _FAILURE_CATEGORIES or field not in _FAILURE_FIELDS:
            raise ValueError("invalid extraction failure metadata")
        super().__init__(message)
        self.category = category
        self.field = field


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


def _validate_quote(
    field: ExtractionFailureField,
    value: object,
    quote: object,
    raw_jd: str,
) -> None:
    if value is None:
        if quote is not None:
            raise ExtractionValidationError(
                f"unknown {field} cannot cite evidence",
                category="evidence_quote",
                field=field,
            )
        return
    if not isinstance(quote, str) or not quote.strip() or quote not in raw_jd:
        raise ExtractionValidationError(
            f"{field} evidence must be an exact nonblank quote",
            category="evidence_quote",
            field=field,
        )
    if isinstance(value, str) and (
        not value.strip() or not re.search(
            rf"(?<!\w){re.escape(value)}(?!\w)", quote, re.IGNORECASE
        )
    ):
        raise ExtractionValidationError(
            f"{field} value must occur in its evidence quote",
            category="evidence_quote",
            field=field,
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


# A salary fact supplies pay context for currency amounts. Mixed funding/count
# strings require an independently governed pay amount with no competing owner.
_AMOUNT = r"(?:\d{1,3}(?:[, ]\d{3})+|\d+)(?:\.\d+)?"
_CURRENCY = r"""(?:[$€£₪]|\b(?:USD|EUR|GBP|ILS|NIS|CAD|AUD|ש[״"']?ח|שקל(?:ים)?)\b)"""
_AMOUNT_UNIT = r"(?:k|m|b|thousand|million|billion|אלף|מיליון)\b"
_MONEY_AMOUNT_RE = re.compile(
    rf"{_CURRENCY}\s*{_AMOUNT}(?:\s*{_AMOUNT_UNIT})?|"
    rf"(?<!\w){_AMOUNT}(?:\s*{_AMOUNT_UNIT})?\s*{_CURRENCY}",
    re.IGNORECASE,
)
_PAY_CONTEXT_RE = re.compile(
    r"\b(?:salary|salaries|base|pay|compensation|rate|wage|OTE|bonus|commissions?|שכר)\b|"
    r"(?:/|\bper\s+)(?:hr|hour|month|year|annum)\b|"
    r"\b(?:annually|monthly|yearly|hourly|בחודש|לחודש|לשנה|בשנה|לשעה)\b",
    re.IGNORECASE,
)
_CONTEXT_AMOUNT_RE = re.compile(
    rf"\b(?:up\s+to|עד)\s+{_AMOUNT}(?![\w%])|"
    rf"(?<!\w){_AMOUNT}\s*(?:k|thousand|אלף)\b|"
    r"\b(?:salary|base|pay|compensation|rate|wage|OTE|שכר|up\s+to|עד)\s*:?\s+(?:is\s+)?"
    r"(?:\d{1,3}(?:[, ]\d{3})+|\d{4,})(?![\w%])|"
    rf"(?<!\w){_AMOUNT}\s*(?:(?:/|per\s+)(?:hr|hour|month|year|annum)\b|"
    r"(?:annually|monthly|yearly|hourly|בחודש|לחודש|לשנה|בשנה|לשעה)\b)",
    re.IGNORECASE,
)
# Qualifiers do not establish pay on their own for small counts or calendar years.
_QUALIFIED_AMOUNT_RE = re.compile(
    rf"\b(?:up\s+to|עד)\s+(?:{_AMOUNT}\s*(?:k|thousand|אלף)\b|"
    r"(?:\d{2,3}(?:[, ]\d{3})+|\d{5,})(?![\w%]))",
    re.IGNORECASE,
)
_RETIREMENT_RE = re.compile(
    r"\b401\s*(?:\(k\)|k)(?!\w)|"
    rf"(?<!\w){_AMOUNT}\s*k\s+(?:retirement|pension)(?:[- ]plan)?\b",
    re.IGNORECASE,
)
_FUNDING_RE = re.compile(
    r"\b(?:raised|funding|series|seed|round|investors?|valuation|ARR|revenue|גייסנו)\b",
    re.IGNORECASE,
)
_NUMERIC_AMOUNT_RE = re.compile(
    rf"{_MONEY_AMOUNT_RE.pattern}|(?<!\w){_AMOUNT}(?:\s*{_AMOUNT_UNIT})?(?!\w)",
    re.IGNORECASE,
)
_AMOUNT_BOUNDARY_RE = re.compile(
    r"[;,\n]|(?<=[.!?])\s+|\b(?:and|but)\b", re.IGNORECASE,
)
_RANGE_JOIN_RE = re.compile(r"\s*(?:[-–—]|to|עד)\s*", re.IGNORECASE)
_PAY_GOVERNOR_RE = re.compile(
    rf"{_PAY_CONTEXT_RE.pattern}|\b(?:up\s+to|עד)\b", re.IGNORECASE,
)
_NON_PAY_RE = re.compile(
    rf"{_FUNDING_RE.pattern}|%|"
    r"\b(?:employees?|customers?|users?|graduates?|headcount|people|"
    r"years|days?|offices?|locations?|retirement|pension|percent|"
    r"עובדים|לקוחות|משתמשים)\b",
    re.IGNORECASE,
)
_PAY_RAISED_RE = re.compile(
    rf"(?P<pay>{_PAY_CONTEXT_RE.pattern})\s+"
    r"(?:(?:was|is|has\s+been|had\s+been|have\s+been)\s+)?raised\s+to\s*$",
    re.IGNORECASE,
)


def has_numeric_salary(value: str) -> bool:
    """Keep numeric compensation unless a competing non-pay owner is attached."""
    value = _RETIREMENT_RE.sub(" ", value)
    has_non_pay = bool(_NON_PAY_RE.search(value))
    amounts = list(_NUMERIC_AMOUNT_RE.finditer(value))
    index = 0
    while index < len(amounts):
        first = last = index
        # A connected range has one context: never accept its ungoverned tail.
        while last + 1 < len(amounts) and _RANGE_JOIN_RE.fullmatch(
            value[amounts[last].end():amounts[last + 1].start()]
        ):
            last += 1
        index = last + 1
        start = amounts[first - 1].end() if first else 0
        end = amounts[index].start() if index < len(amounts) else len(value)
        before = value[start:amounts[first].start()]
        after = value[amounts[last].end():end]
        before = _AMOUNT_BOUNDARY_RE.split(before)[-1]
        after = _AMOUNT_BOUNDARY_RE.split(after)[0]
        # Collapse only an explicit pay-subject increase, including auxiliaries.
        # Other funding/count governors in the window still veto this amount.
        before = _PAY_RAISED_RE.sub(r"\g<pay> ", before)
        before = " ".join(before.split()[-4:]) + " "
        after = " " + " ".join(after.split()[:4])
        context = before + value[amounts[first].start():amounts[last].end()] + after
        if _NON_PAY_RE.search(context):
            continue
        # Without competing non-pay wording, currency already identifies pay.
        # Otherwise require pay ownership in this candidate's bounded window.
        if has_non_pay and not _PAY_GOVERNOR_RE.search(before + after):
            continue
        # Endpoints share an explicit currency or K unit; otherwise each must
        # independently meet the earlier unmarked-amount rules.
        if _MONEY_AMOUNT_RE.search(context) or _QUALIFIED_AMOUNT_RE.search(context) or (
            _PAY_CONTEXT_RE.search(context) and (
                re.search(rf"{_AMOUNT}\s*(?:k|thousand|אלף)\b", context, re.IGNORECASE)
                or all(_CONTEXT_AMOUNT_RE.search(before + amount.group() + after)
                       for amount in amounts[first:index])
            )
        ):
            return True
    return False


def normalize_salary(facts: dict[str, object], raw_jd: str) -> None:
    """Retain source-supported nonnumeric pay wording only as a raw remark."""
    salary = facts["salary"]
    assert isinstance(salary, dict)
    value = salary["value"]
    _validate_quote("salary", value, salary["evidence_quote"], raw_jd)
    if isinstance(value, str) and not has_numeric_salary(value):
        facts["salary_remark"] = value
        facts["salary"] = {"value": None, "evidence_quote": None}


def validate_facts(facts: dict[str, object], raw_jd: str) -> None:
    """Reject extracted facts that are not supported by their source quotes."""

    for field in ("location", "remote", "seniority", "salary"):
        fact = facts[field]
        assert isinstance(fact, dict)
        _validate_quote(field, fact["value"], fact["evidence_quote"], raw_jd)
    salary = facts["salary"]["value"]
    if salary is not None and not has_numeric_salary(salary):
        raise ExtractionValidationError(
            "salary requires numeric compensation evidence",
            category="evidence_quote", field="salary",
        )
    if "salary_remark" in facts:
        remark = facts["salary_remark"]
        _validate_quote("salary", remark, remark, raw_jd)
        if not isinstance(remark, str) or has_numeric_salary(remark):
            raise ExtractionValidationError(
                "salary remark must contain nonnumeric source wording",
                category="evidence_quote", field="salary",
            )
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
        _validate_quote("stack", value, quote, raw_jd)
        assert isinstance(value, str)
        normalized = value.strip().casefold()
        if normalized in seen:
            raise ExtractionValidationError(
                "stack facts must be unique",
                category="stack_uniqueness",
                field="stack",
            )
        seen.add(normalized)
