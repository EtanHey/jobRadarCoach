"""Numeric salary spans, amount ownership, and source-preserving normalization."""

from __future__ import annotations

import re

from extractor.quotes import ExtractionValidationError, validate_quote

# A salary fact supplies pay context for currency amounts. Mixed funding/count
# strings require an independently governed pay amount with no competing owner.
_AMOUNT = r"(?:\d{1,3}(?:[, ]\d{3})+|\d+)(?:\.\d+)?"
_CURRENCY = r"""(?:(?:US|CA|AU)?[$]|[€£₪]|\b(?:USD|EUR|GBP|ILS|NIS|CAD|AUD|ש[״"']?ח|שקל(?:ים)?)\b)"""
_AMOUNT_UNIT = r"(?:k|m|b|thousand|million|billion|אלף|מיליון)\b"
_MONEY_AMOUNT_RE = re.compile(
    rf"{_CURRENCY}\s*{_AMOUNT}(?:\s*{_AMOUNT_UNIT})?(?:\s*{_CURRENCY})?|"
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
    r"\b(?:raised|funding|series|seed|round|investors?|valuation|ARR|revenue|"
    r"גייסנו|הכנסות|מחזור)\b",
    re.IGNORECASE,
)
_NUMERIC_AMOUNT_RE = re.compile(
    rf"{_MONEY_AMOUNT_RE.pattern}|(?<!\w){_AMOUNT}(?:\s*{_AMOUNT_UNIT})?(?!\w)",
    re.IGNORECASE,
)
_AMOUNT_BOUNDARY_RE = re.compile(
    r"[;,\n]|(?<=[.!?])\s+|\b(?:and|but)\b", re.IGNORECASE,
)
_RANGE_JOIN_RE = re.compile(r"\s*(?:[-–—]|to|and|עד)\s*", re.IGNORECASE)
_NON_PAY_RE = re.compile(
    rf"{_FUNDING_RE.pattern}|%|"
    r"\bbase\s+(?:of|is)\b|"
    r"\b(?:customers?|users?|graduates?|headcount|people|investment|capital|"
    r"years|days?|offices?|retirement|pension|percent|לקוחות|משתמשים)\b|"
    rf"(?<!\w){_AMOUNT}\s*(?:(?:k|thousand|אלף)\s*)?(?:employees?|locations?|עובדים)\b",
    re.IGNORECASE,
)
_PAY_RAISED_RE = re.compile(
    rf"(?P<pay>{_PAY_CONTEXT_RE.pattern})\s+"
    r"(?:(?:was|is|has\s+been|had\s+been|have\s+been)\s+)?raised\s+to\s*$",
    re.IGNORECASE,
)


# Pay ownership must touch the amount. Bare "base" before a number can describe
# a customer/capital base; after an amount it cannot introduce a non-pay noun.
_PAY_BEFORE_RE = re.compile(
    r"\b(?:(?:base\s+|hourly\s+)?(?:salary|salaries|pay|comp(?:ensation)?|rate|wage|OTE|bonus|"
    r"commissions?|ו?שכר)(?:\s+range)?"
    r"(?:\s+(?:(?:was|is|has\s+been|had\s+been|have\s+been)\s+)?raised\s+to|"
    r"\s+הועלה\s+ל-?)?(?:\s+(?:is|of))?(?:\s+(?:up\s+to|עד))?|up\s+to|עד)"
    r"\s*[:(]?\s*$",
    re.IGNORECASE,
)
_PAY_AFTER_RE = re.compile(
    r"^\s*(?:base(?:\s+(?:salary|pay|comp(?:ensation)?)\b|(?=\s*(?:$|[).!?])))|"
    r"salary|pay|compensation|(?:signing\s+)?bonus|commissions?|שכר|"
    r"(?:\+?\s*/|per\s+)(?:hr|hour|month|year|annum)|"
    r"annually|monthly|yearly|hourly|בחודש|לחודש|לשנה|בשנה|לשעה)\b",
    re.IGNORECASE,
)
_CLAUSE_BOUNDARY_RE = re.compile(r"[;\n]|,(?!\d)|(?<=[.!?])\s+")
_OWNERSHIP_BOUNDARY_RE = re.compile(r"[;\n]|(?<=[.!?])\s+")
_EXPLICIT_PAY_AFTER_RE = re.compile(
    r"^\s*(?:base\s+(?:salary|pay|comp(?:ensation)?)|salary|pay|compensation|שכר)\b",
    re.IGNORECASE,
)


def _adjacent_ownership_veto(before: str, amount: str, after: str) -> bool:
    if re.match(r"\s*base\b", after, re.IGNORECASE) and not _PAY_AFTER_RE.search(after):
        return True
    governed_before = _PAY_RAISED_RE.sub(r"\g<pay> ", before)
    return bool(_NON_PAY_RE.search(governed_before + amount + after))


def _has_explicit_pay_owner(before: re.Match[str] | None, after: str) -> bool:
    return bool(
        (before and not re.match(r"(?:up\s+to|עד)\b", before.group(), re.IGNORECASE))
        or _EXPLICIT_PAY_AFTER_RE.search(after)
    )


def _inherits_non_pay_owner(scanned: str, left: int, clause_start: int) -> bool:
    # Commas separate amounts without establishing a new subject.
    ownership_start = max(
        (m.end() for m in _OWNERSHIP_BOUNDARY_RE.finditer(scanned, 0, left)), default=0,
    )
    return bool(_NON_PAY_RE.search(scanned[ownership_start:clause_start]))


def salary_span(value: str | None) -> str | None:
    """Select one source pay span, retaining whole clauses for ownership checks."""
    if value is None:
        return None
    scanned = _RETIREMENT_RE.sub(lambda m: " " * len(m.group()), value)
    has_non_pay = bool(_NON_PAY_RE.search(scanned))
    amounts = list(_NUMERIC_AMOUNT_RE.finditer(scanned))
    index = 0
    while index < len(amounts):
        first = last = index
        # A connected range has one context: never accept its ungoverned tail.
        while last + 1 < len(amounts) and _RANGE_JOIN_RE.fullmatch(
            scanned[amounts[last].end():amounts[last + 1].start()]
        ):
            last += 1
        index = last + 1
        left, right = amounts[first].start(), amounts[last].end()
        clause_start = max(
            (m.end() for m in _CLAUSE_BOUNDARY_RE.finditer(scanned, 0, left)), default=0,
        )
        boundary = _CLAUSE_BOUNDARY_RE.search(scanned, right)
        clause_end = boundary.start() if boundary else len(scanned)
        clause = scanned[clause_start:clause_end]
        start = max(clause_start, amounts[first - 1].end() if first else 0)
        end = min(clause_end, amounts[index].start() if index < len(amounts) else len(scanned))
        before = scanned[start:left]
        after = scanned[right:end]
        before = _AMOUNT_BOUNDARY_RE.split(before)[-1]
        # Parentheses can name this amount's owner; additions can name another.
        ownership_after = re.split(
            r"\+(?!\s*/)|\b(?:and|but)\b", after, maxsplit=1, flags=re.IGNORECASE,
        )[0]
        after = ownership_after.split("(", 1)[0]
        pay_before = _PAY_BEFORE_RE.search(before)
        pay_after = _PAY_AFTER_RE.search(after)
        if _adjacent_ownership_veto(before, scanned[left:right], ownership_after):
            continue
        governed_before = _PAY_RAISED_RE.sub(r"\g<pay> ", before)
        context = governed_before + scanned[left:right] + after
        # A comma does not reset revenue/ARR ownership. Only a fresh pay noun
        # can claim the next amount; "up to", cadence and bare "base" cannot.
        if _inherits_non_pay_owner(scanned, left, clause_start) and not (
            _has_explicit_pay_owner(pay_before, after)
        ):
            continue
        # A cadence cannot take an inherited revenue/funding amount; a fresh
        # adjacent pay noun can establish ownership after an earlier amount.
        if _NON_PAY_RE.search(clause) and not (pay_before or (
            pay_after and re.match(r"\s*(?:base|salary|pay|compensation|שכר)\b", after, re.IGNORECASE)
        )):
            continue
        if has_non_pay and not (pay_before or pay_after):
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
            span_start = (left - len(before) + pay_before.start()
                          if pay_before and not pay_before.group().rstrip().endswith("(") else left)
            span_end = right + pay_after.end() if pay_after else right
            return value[span_start:span_end].strip()
    return None


def has_numeric_salary(value: str) -> bool:
    """Keep numeric compensation unless a competing non-pay owner is attached."""
    return salary_span(value) is not None


def normalize_salary(facts: dict[str, object], raw_jd: str) -> None:
    """Store the source pay span and preserve trimmed or rejected text as a remark."""
    salary = facts["salary"]
    if not isinstance(salary, dict):
        raise ExtractionValidationError(
            "salary fact must be an object", category="evidence_quote", field="salary",
        )
    value = salary["value"]
    validate_quote("salary", value, salary["evidence_quote"], raw_jd)
    if isinstance(value, str):
        # Quote validation already found this value case-insensitively. Preserve
        # the JD spelling for both the accepted pay span and any raw remark.
        value = re.search(
            rf"(?<!\w){re.escape(value)}(?!\w)",
            salary["evidence_quote"], re.IGNORECASE,
        ).group()
        span = salary_span(value)
        if span != value:
            facts["salary_remark"] = value
            facts["salary"] = {
                "value": span,
                "evidence_quote": salary["evidence_quote"] if span else None,
            }
