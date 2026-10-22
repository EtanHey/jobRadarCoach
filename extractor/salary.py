"""Numeric salary spans, amount ownership, and source-preserving normalization."""

from __future__ import annotations

import logging
import re

from extractor.quotes import ExtractionValidationError, validate_quote

LOGGER = logging.getLogger("coach.jobfeed.extractor")

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
# Closed pay vocabulary. A bare rate/base and business-metric nouns cannot
# acquire pay ownership merely because a currency or cadence follows them.
_PAY_NOUN = r"(?:salary|salaries|base\s+(?:salary|pay|comp(?:ensation)?)|pay|compensation|wage|OTE|(?:hourly|daily|day)\s+rate|gross|net|ו?שכר|ברוטו|נטו)"
_CADENCE = r"(?:(?:/|\bper\s+)(?:hr|hour|day|month|year|annum|yr|mo)\b|\b(?:annually|monthly|yearly|hourly|daily|בחודש|לחודש|לשנה|בשנה|לשעה)\b)"
_PAY_CONTEXT_RE = re.compile(rf"\b{_PAY_NOUN}\b|{_CADENCE}", re.IGNORECASE)
_CONTEXT_AMOUNT_RE = re.compile(
    rf"\b(?:up\s+to|עד)\s+{_AMOUNT}(?![\w%])|"
    rf"(?<!\w){_AMOUNT}\s*(?:k|thousand|אלף)\b|"
    rf"\b{_PAY_NOUN}\s*:?\s+(?:is\s+)?{_AMOUNT}(?![\w%])|"
    rf"(?<!\w){_AMOUNT}\s*{_CADENCE}",
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
    r"[;,\n&]|(?<=[.!?])\s+|\b(?:and|but)\b", re.IGNORECASE,
)
_RANGE_JOIN_RE = re.compile(r"\s*(?:[-–—]|to|and|עד)\s*", re.IGNORECASE)
_NON_PAY_RE = re.compile(
    rf"{_FUNDING_RE.pattern}|%|"
    r"\bbase\s+(?:of|is)\b|"
    r"\b(?:customers?|users?|graduates?|headcount|people|investment|capital|"
    r"years|offices?|retirement|pension|percent|לקוחות|משתמשים)\b|"
    rf"(?<!\w){_AMOUNT}\s*(?:(?:k|thousand|אלף)\s*)?(?:employees?|locations?|עובדים)\b",
    re.IGNORECASE,
)
_PAY_RAISED_RE = re.compile(
    rf"(?P<pay>{_PAY_CONTEXT_RE.pattern}|\brate)\s+"
    r"(?:(?:was|is|has\s+been|had\s+been|have\s+been)\s+)?raised\s+to\s*$",
    re.IGNORECASE,
)


# Pay ownership must touch the amount. Bare "base" before a number can describe
# a customer/capital base; after an amount it cannot introduce a non-pay noun.
_PAY_BEFORE_RE = re.compile(
    rf"\b(?:(?:{_PAY_NOUN}|rate)(?:\s+range|\s+בסיס\s+של)?"
    r"(?:\s+(?:(?:was|is|has\s+been|had\s+been|have\s+been)\s+)?raised\s+to|"
    r"\s+הועלה\s+ל-?)?(?:\s+(?:is|of))?(?:\s+(?:up\s+to|עד))?|up\s+to|עד)"
    r"\s*[:(]?\s*$",
    re.IGNORECASE,
)
_PAY_AFTER_RE = re.compile(
    rf"^\s*(?:(?:(?:annual|monthly|hourly|daily)\s+)?{_PAY_NOUN}\b(?:\s+range)?|\+?\s*{_CADENCE}|"
    # Terminal base qualifies an otherwise unopposed currency amount. It never
    # establishes ownership for a number or overrides a preceding metric.
    r"base\b(?=\s*(?:$|[).!?])))",
    re.IGNORECASE,
)
_CLAUSE_BOUNDARY_RE = re.compile(r"[;\n]|,(?!\d)|(?<=[.!?])\s+")
_OWNERSHIP_BOUNDARY_RE = re.compile(r"\n|(?<=[.!?])\s+")
_EXPLICIT_PAY_AFTER_RE = re.compile(rf"^\s*{_PAY_NOUN}\b", re.IGNORECASE)
_UNOWNED_PREFIX_RE = re.compile(r"\s*(?:(?:up\s+to|between|from|or|עד)\s*)?[:(=\s]*$", re.IGNORECASE)
# Geographic/role band labels do not own a business quantity. Keep this
# separate from the pay vocabulary so labels cannot override metric ownership.
_REGION_PREFIX_RE = re.compile(
    r"\s*(?:(?:California|Washington|New York|New Jersey|Connecticut|Canada|"
    r"MA|NYC/NJ|DC Metro|All other (?:U\.S\. |US )?(?:states|Locations)|"
    r"(?:US|Canadian) employees \(any location\)):\s*(?:Senior [IV]+:\s*)?|Senior [IV]+:\s*)$",
    re.IGNORECASE,
)
_BAND_NOTE_RE = re.compile(
    r"\s*(?:\((?:base|entry-level qualifications|highly experienced)\)|"
    r"in (?:local currency|our (?:lowest|highest) geographic market)(?:\s+up\s+to)?|"
    r"or more(?:, depending on experience)?|DOE)\s*[-–—]?\s*$",
    re.IGNORECASE,
)


def _has_unknown_governor(before: str, after: str) -> bool:
    # List punctuation does not erase the label immediately before an amount.
    before = re.sub(r"[,;/–—\s-]+$", " ", before)
    pay = _PAY_BEFORE_RE.search(before)
    if _has_explicit_pay_owner(pay, ""):
        return False
    # A bare rate has no pay meaning without its adjacent closed cadence.
    if _PAY_AFTER_RE.search(after) and re.fullmatch(
        r"\s*rate(?:\s+raised\s+to)?\s*", before, re.IGNORECASE,
    ):
        return False
    return not (_UNOWNED_PREFIX_RE.fullmatch(before) or _REGION_PREFIX_RE.fullmatch(before))


def _adjacent_ownership_veto(before: str, amount: str, after: str) -> bool:
    if re.match(r"\s*base\b", after, re.IGNORECASE) and not _PAY_AFTER_RE.search(after):
        return True
    governed_before = _PAY_RAISED_RE.sub(r"\g<pay> ", before)
    return bool(_NON_PAY_RE.search(governed_before + amount + after))


def _has_explicit_pay_owner(before: re.Match[str] | None, after: str) -> bool:
    return bool(
        (before and re.match(rf"{_PAY_NOUN}\b", before.group(), re.IGNORECASE))
        or _EXPLICIT_PAY_AFTER_RE.search(after)
    )


def _inherits_non_pay_owner(scanned: str, left: int, after: str) -> bool:
    ownership_start = max(
        (m.end() for m in _OWNERSHIP_BOUNDARY_RE.finditer(scanned, 0, left)), default=0,
    )
    prefix = scanned[ownership_start:left]
    previous = list(_NUMERIC_AMOUNT_RE.finditer(prefix))
    if previous and _NON_PAY_RE.search(prefix[:previous[-1].end()]):
        return True
    for index, amount in enumerate(previous):
        start = previous[index - 1].end() if index else 0
        before = prefix[start:amount.start()]
        if _has_unknown_governor(before, prefix[amount.end():]):
            return True
    # Include the pending amount's governor even when no earlier amount exists.
    start = previous[-1].end() if previous else 0
    return _has_unknown_governor(prefix[start:], after)


def salary_span(value: str | None) -> str | None:
    """Check governor, suffix, veto, inherited owner, non-pay gate, then money."""
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
        start = max(clause_start, amounts[first - 1].end() if first else 0)
        end = min(clause_end, amounts[index].start() if index < len(amounts) else len(scanned))
        before = scanned[start:left]
        after = scanned[right:end]
        before = _AMOUNT_BOUNDARY_RE.split(before)[-1]
        # Parentheses can name this amount's owner; additions can name another.
        ownership_after = re.split(
            r"\+(?!\s*/)|\b(?:and|but|plus)\b", after, maxsplit=1, flags=re.IGNORECASE,
        )[0]
        after = ownership_after.split("(", 1)[0]
        pay_before = _PAY_BEFORE_RE.search(before)
        pay_after = _PAY_AFTER_RE.search(after)
        if _has_unknown_governor(before, after):
            continue
        suffix = ownership_after[pay_after.end():] if pay_after else ownership_after
        if re.search(r"[^\W\d_]", suffix) and not (
            _BAND_NOTE_RE.fullmatch(suffix) or _REGION_PREFIX_RE.fullmatch(suffix)
        ):
            continue
        if _adjacent_ownership_veto(before, scanned[left:right], ownership_after):
            continue
        governed_before = _PAY_RAISED_RE.sub(r"\g<pay> ", before)
        context = governed_before + scanned[left:right] + after
        # List punctuation preserves ownership, including before a first amount.
        # Only a fresh pay noun can supersede it; cadence/qualifiers cannot.
        if _inherits_non_pay_owner(scanned, left, after) and not (
            _has_explicit_pay_owner(pay_before, after)
        ):
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
    """Degrade salary failures locally, retaining only source-supported raw text."""
    salary = facts.get("salary")
    value = salary.get("value") if isinstance(salary, dict) else salary
    quote = salary.get("evidence_quote") if isinstance(salary, dict) else None
    remark = facts.get("salary_remark")
    source = None
    if isinstance(value, str) and value.strip():
        # Prefer the provider's exact source quote and spelling. If that quote
        # failed, the raw JD can still support the rejected text as a remark.
        haystack = quote if isinstance(quote, str) and quote in raw_jd else raw_jd
        match = re.search(rf"(?<!\w){re.escape(value)}(?!\w)", haystack, re.IGNORECASE)
        if match:
            source = match.group()
    try:
        if not isinstance(salary, dict) or set(salary) != {"value", "evidence_quote"}:
            raise ExtractionValidationError(
                "salary fact must be an object", category="evidence_quote", field="salary",
            )
        if (value is not None and (not isinstance(value, str) or len(value) > 256)) or (
            isinstance(quote, str) and len(quote) > 1000
        ):
            raise ExtractionValidationError(
                "salary value must be text", category="evidence_quote", field="salary",
            )
        validate_quote("salary", value, quote, raw_jd)
        if remark is not None:
            validate_quote("salary", remark, remark, raw_jd)
            if not isinstance(remark, str):
                raise ExtractionValidationError(
                    "salary remark must be text", category="evidence_quote", field="salary",
                )
        span = salary_span(source)
        if span is not None:
            validate_quote("salary", span, quote, raw_jd)
            if salary_span(span) != span or (remark is not None and salary_span(remark) != span):
                raise ExtractionValidationError(
                    "salary span must be stable", category="evidence_quote", field="salary",
                )
    except ExtractionValidationError:
        span = None
        if source is None and isinstance(quote, str) and quote.strip() and quote in raw_jd:
            source = quote
        # A failed salary must not lose independently supported facts, or turn
        # unsupported provider text into a persisted source remark.
        remark = None
    if span is None and salary != {"value": None, "evidence_quote": None}:
        LOGGER.warning("extraction_fact_dropped field=salary category=evidence_quote")
    facts["salary"] = {"value": span, "evidence_quote": quote if span else None}
    if source is not None and span != source:
        remark = source
    if span is None and isinstance(remark, str):
        remark = remark[:1000]
    if isinstance(remark, str) and remark.strip() and remark in raw_jd:
        facts["salary_remark"] = remark
    else:
        facts.pop("salary_remark", None)
