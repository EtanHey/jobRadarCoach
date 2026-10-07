"""Fixed, cheap JD rules calibrated against owner Pursue labels. No model I/O."""
import re

VERSION = '2026-10-07-v3'
OPTIONAL = r'\b(?:advantage|bonus|nice[ -]to[ -]have|plus|preferred|optional)\b|יתרון'
ALTERNATIVE = r'\b(?:or|such as|e\.g\.?|for example|one of|including)\b|כגון|לדוגמה|או'
REQUIRED = r'\b(?:required|mandatory|must|proficien\w*|strong|deep|extensive|advanced|proven|expert\w*|\d+\+?\s+years?|experience\s+(?:in|with))\b'


def matches(pattern: str, text: str) -> bool:
    return bool(re.search(pattern, text, re.I))


def already_us_resident(jd: str) -> bool:
    """Require explicit existing applicant residency, not future relocation."""
    text = re.sub(r'[*_`]', '', jd or '')
    pattern = r'\b(?:must|(?:candidates?|applicants?|you)\s+(?:must|should|need to|are required to))\s+already\s+(?:live|reside|be based|be living|be residing)\s+in\s+(?:the\s+)?(?:us|usa|united states)\b'
    for clause in re.split(r'\n|[;•]|(?<=[.!?])\s+(?=[A-Z])', text):
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
    for clause in (c.strip() for c in re.split(r'\n|[;•]|(?<=[.!?])\s+(?=[A-Z])', text)):
        if matches(OPTIONAL, clause):
            continue
        if matches(r'\bequity[ -]only\b', clause):
            return 'equity-only'
        years = re.match(r'^(?:[-–*]\s*)?(?:(?:minimum(?: of)?|at least|must have|you have)\s+)?(?P<minimum>\d{1,2})\s*(?:\+|[-–]\s*\d{1,2}|\s+or more)?\s+years?\b.{0,90}\b(?:experience|expertise|developing|building|leading|managing|working)\b', clause, re.I)
        if years and int(years['minimum']) >= 7 and not matches(r'\b(?:company|business|founded|history|our|we)\b', clause):
            return 'years-minimum-7-strict'
        if not matches(r'\bequivalent\b', clause) and matches(r'\b(?:bsc|b\.?sc\.?|bachelor\S*|degree)\b', clause) and matches(r'\b(?:required|mandatory|must hold|must have)\b', clause):
            return 'mandatory-degree'
        if not matches(ALTERNATIVE, clause) and matches(r'\bmarketing background\b|\bSAP\s+(?:ABAP|development)\b|\b\d+\+?\s+years?\b.{0,40}\bbuilding security solutions\b', clause) and matches(REQUIRED, clause):
            return 'specialist-required'
    return None


def refresh_gate(connection, *, posting_ids=(), limit: int = 1000) -> None:
    """Classify backlog; only explicit US residency overrides a prior score."""
    rows = connection.execute(
        "select p.id::text,p.title,p.raw_jd,exists(select 1 from public.posting_scores gs where gs.posting_id=p.id) from public.postings p "
        "where p.relevance_gate->>'version' is distinct from %s "
        "and not coalesce((p.relevance_gate->>'override')::boolean,false) "
        "and p.raw_jd is not null and length(trim(p.raw_jd))>=80 "
        "and (not exists(select 1 from public.posting_scores s where s.posting_id=p.id) or p.raw_jd ilike '%%already%%') "
        "and not exists(select 1 from public.posting_status st where st.posting_id=p.id and st.status='applied') "
        "and (%s::uuid[] is null or p.id=any(%s::uuid[])) order by p.first_seen_at,p.id limit %s",
        (VERSION, list(posting_ids) or None, list(posting_ids) or None, limit),
    ).fetchall()
    for posting_id, title, jd, has_score in rows:
        # Owner's explicit rejection wins over an automated score proxy. Applied
        # rows and every other already-scored role keep their original protection.
        rule = ('already-us-resident' if already_us_resident(jd) else None) if has_score else gate_rule(title, jd)
        connection.execute(
            "update public.postings p set relevance_gate=jsonb_build_object('version',%s::text,'rule',%s::text) "
            "where p.id=%s and p.title=%s and p.raw_jd=%s "
            "and not coalesce((p.relevance_gate->>'override')::boolean,false) "
            "and (not exists(select 1 from public.posting_scores s where s.posting_id=p.id) or %s::boolean) "
            "and not exists(select 1 from public.posting_status st where st.posting_id=p.id and st.status='applied')",
            (VERSION, rule, posting_id, title, jd, has_score or rule in (None, 'already-us-resident')),
        )


# Unexamined backlog waits for the next bounded pass. Existing scored/applied
# history is protected except the owner-confirmed explicit US-residency rule.
SELECTION_GUARD = (
    "and not p.relevance_filtered "
    "and (p.relevance_gate->>'version' = %s "
    "or coalesce((p.relevance_gate->>'override')::boolean,false) "
    "or exists(select 1 from public.posting_scores gs where gs.posting_id=p.id) "
    "or exists(select 1 from public.posting_status gst where gst.posting_id=p.id and gst.status='applied')) "
)
