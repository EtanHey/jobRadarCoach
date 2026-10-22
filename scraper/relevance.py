"""Fixed, cheap JD rules calibrated against owner Pursue labels. No model I/O."""
import json
import re
try:
    from scraper.years import blocking_hebrew_years, normalize_english_years
    from scraper.jd_quality import jd_quality_rule
except ModuleNotFoundError:
    from years import blocking_hebrew_years, normalize_english_years
    from jd_quality import jd_quality_rule

VERSION = '2026-10-22-v9-years-jdq'
PURSUIT_STATUSES = frozenset({
    'worth_checking', 'applied', 'screen', 'interview_technical',
    'interview_final', 'offer', 'contract', 'rejected',
})
_PURSUIT_SQL = ','.join(f"'{status}'" for status in sorted(PURSUIT_STATUSES))
OPTIONAL = r'\b(?:advantage|bonus|nice[ -]to[ -]have|plus|preferred|optional)\b|יתרון'
ALTERNATIVE = r'\b(?:or|such as|e\.g\.?|for example|one of|including)\b|כגון|לדוגמה|או'
REQUIRED = r'\b(?:required|mandatory|must|proficien\w*|strong|deep|extensive|advanced|proven|expert\w*|\d+\+?\s+years?|experience\s+(?:in|with))\b'
NEGATED_REQUIREMENT = (
    r"\b(?:not|never|(?:is|are|was|were|do|does|did)n['’]t)\s+(?:strictly\s+)?(?:required|mandatory)\b"
    r"|\bno\s+(?:(?:formal|academic|college|university|bachelor['’]?s?|master['’]?s?|b\.?sc\.?)\s+)*degrees?\b"
)


CLAUSE_BOUNDARY = r'\n|[;•]|(?<=[.!?])\s+(?=[A-Z])'


def matches(pattern: str, text: str) -> bool:
    return bool(re.search(pattern, text, re.I))


def already_us_resident(jd: str) -> bool:
    """Require explicit existing applicant residency, not future relocation."""
    text = re.sub(r'[*_`]', '', jd or '')
    pattern = r'\b(?:must|(?:candidates?|applicants?|you)\s+(?:must|should|need to|are required to))\s+already\s+(?:live|reside|be based|be living|be residing)\s+in\s+(?:the\s+)?(?:us|usa|united states)\b'
    for clause in re.split(CLAUSE_BOUNDARY, text):
        if matches(OPTIONAL, clause) or matches(r'\bor\b.{0,35}\b(?:relocat\w*|move|moving)\b', clause):
            continue
        if matches(pattern, clause):
            return True
    return False


def gate_rule(title: str, jd: str) -> str | None:
    """Return the first rejection rule; ambiguous or unstated requirements pass."""
    text = re.sub(r'[*_`]', '', jd or '')
    if already_us_resident(text):
        return 'already-us-resident'
    if not matches(r'\b(?:front[ -]?end|full[ -]?stack|product engineer|ai|agents?)\b', title):
        if matches(r'\b(?:qa|quality assurance|software tester)\b', title):
            return 'pure-qa-title'
        if matches(r'\b(?:technical support|customer support|help[ -]?desk|support engineer)\b', title):
            return 'support-title'
    if matches(r'\b(?:technical co[ -]?founder|chief technology officer|cto)\b', title):
        return 'technical-cofounder-title'
    if matches(r'\b(?:staff|principal|head[ -]+of|lead|team lead|tech lead|technical leader|engineering manager)\b', title):
        if not matches(r'\b(?:junior|mid[ -]?level|senior)\b.{0,35}(?:\bto\b|\bthrough\b|\bor\b|/).{0,15}\b(?:staff|principal|lead)\b', title):
            return 'leadership-title-strict'
    if matches(r'(?:\bjava\b|\bangular\b|c\+\+|c#|\.net\b)\s+(?:software\s+)?(?:developer|engineer)\b|\b(?:developer|engineer)\s*[-–(]\s*(?:java\b|angular\b|c\+\+|c#|\.net\b)', title):
        return 'incompatible-stack-title'
    # Profile-role removal and Data-family rules remain OFF pending rulings #2/#3.
    if blocking_hebrew_years(text):
        return 'years-minimum-7-strict'
    for clause in (c.strip() for c in re.split(CLAUSE_BOUNDARY, text)):
        clause = normalize_english_years(clause)
        if matches(OPTIONAL + '|' + NEGATED_REQUIREMENT, clause):
            continue
        if matches(r'\bequity[ -]only\b', clause) and not matches(r'\bnot\s+(?:(?:an?|purely|solely)\s+)?equity[ -]only\b', clause):
            return 'equity-only'
        years = re.match(r'^(?:[-–*]\s*)?(?:(?:minimum(?: of)?|at least|must have|you have)\s+)?(?P<minimum>\d{1,2})\s*(?:\+|[-–]\s*\d{1,2}|\s+or more)?\s+years?\b.{0,90}\b(?:experience|expertise|developing|building|leading|managing|working)\b', clause, re.I)
        if years and int(years['minimum']) >= 7 and not matches(r'\b(?:company|business|founded|history|our|we)\b', clause):
            return 'years-minimum-7-strict'
        if not matches(r'\bequivalent\b|\bdegree\s+of\b', clause) and matches(r'\b(?:bsc|b\.?sc\.?|bachelor\S*|degree)\b', clause) and matches(r'\b(?:required|mandatory|must hold|must have)\b', clause):
            return 'mandatory-degree'
        if not matches(ALTERNATIVE, clause) and matches(r'\bmarketing background\b|\bSAP\s+(?:ABAP|development)\b|\b\d+\+?\s+years?\b.{0,40}\bbuilding security solutions\b', clause) and matches(REQUIRED, clause):
            return 'specialist-required'
    return None


def refresh_gate(connection, *, posting_ids=(), limit: int = 1000, at_write: bool = False) -> None:
    """Classify backlog or a cloud write batch before its transaction commits."""
    if at_write and not posting_ids:
        return  # An empty harvest must never turn into a backlog scan.
    # Only changed decisions take the posting lock. Re-read after acquiring it
    # and recheck status in the UPDATE so a concurrent Pursue still wins.
    with connection.transaction():
        _refresh_gate_locked(connection, posting_ids=posting_ids, limit=limit, at_write=at_write)


def _classified_gate(row):
    _, title, jd, has_score, gate = row
    # Explicit residency wins over a score proxy, never a pipeline decision.
    rule = ('already-us-resident' if already_us_resident(jd) else None) if has_score else gate_rule(title, jd)
    # A prior score cannot establish that its source was a usable single-role JD.
    return {**gate, 'version': VERSION, 'rule': jd_quality_rule(jd) or rule}


_GATE_ROW = (
    "select p.id::text,p.title,p.raw_jd,"
    "exists(select 1 from public.posting_scores gs where gs.posting_id=p.id),"
    "p.relevance_gate from public.postings p "
)
_NOT_PURSUED = (
    "and not exists(select 1 from public.posting_status st "
    f"where st.posting_id=p.id and st.status in ({_PURSUIT_SQL})) "
)


def _refresh_gate_locked(connection, *, posting_ids, limit, at_write):
    rows = connection.execute(
        _GATE_ROW + "where (%s::boolean or p.relevance_gate->>'version' is distinct from %s) "
        "and not coalesce((p.relevance_gate->>'override')::boolean,false) "
        + _NOT_PURSUED +
        "and (%s::uuid[] is null or p.id=any(%s::uuid[])) order by p.first_seen_at,p.id limit %s",
        (at_write, VERSION, list(posting_ids) or None, list(posting_ids) or None, limit),
    ).fetchall()
    for row in rows:
        if _classified_gate(row) == row[4]:
            continue
        # The unlocked read lets identical at-write decisions avoid both an
        # UPDATE and its row lock. Changed rows retain set_status serialization.
        locked = connection.execute(
            _GATE_ROW + "where p.id=%s for update of p", (row[0],),
        ).fetchone()
        if locked is None or locked[4].get('override'):
            continue
        desired = _classified_gate(locked)
        if desired == locked[4]:
            continue
        posting_id, title, jd, has_score, _ = locked
        connection.execute(
            "update public.postings p set relevance_gate=%s::jsonb "
            "where p.id=%s and p.title=%s and p.raw_jd is not distinct from %s "
            "and not coalesce((p.relevance_gate->>'override')::boolean,false) "
            "and (not exists(select 1 from public.posting_scores s where s.posting_id=p.id) or %s::boolean) "
            + _NOT_PURSUED,
            (json.dumps(desired), posting_id, title, jd, has_score or desired['rule'] in (None, 'already-us-resident')),
        )


# Unexamined backlog waits for the next bounded pass. Pipeline choices always
# win; dismissals must pass the gate, and scores still honor US residency.
SELECTION_GUARD = (
    "and not p.relevance_filtered "
    "and (p.relevance_gate->>'version' = %s "
    "or coalesce((p.relevance_gate->>'override')::boolean,false) "
    "or exists(select 1 from public.posting_scores gs where gs.posting_id=p.id) "
    f"or exists(select 1 from public.posting_status gst where gst.posting_id=p.id and gst.status in ({_PURSUIT_SQL}))) "
)
