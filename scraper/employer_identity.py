"""Conservative role attribution, with publisher self-description across the JD."""
from __future__ import annotations

import re

from scraper.ats_sources import ATS_SOURCES
from scraper.employer_publishers import PUBLISHERS
from scraper.employer_aliases import ALIASES, is_alias

VERSION = '9'
PUBLISHER_KEYS = frozenset(p.casefold() for p in PUBLISHERS)
# Reviewed staffing intermediaries whose names do not identify their business.
STAFFING_KEYS = PUBLISHER_KEYS | {'alldus', 'mertens - malamteam'}
# Reviewed against all 57 family-2 evidence IDs; these are publishers, not clients.
NAME = r'(?P<name>[A-Z][\w·&.,’\'() \t-]{0,78}?)'
PATTERNS = [
    re.compile(r'^(?:Recruiting |Hiring |We are recruiting )?on behalf of\s+\*{0,2}' + NAME + r'\*{0,2}(?=\s+(?:for|is|are|we)\b|[,:;\n]|$)', re.M),
    re.compile(r'^(?:Our|our) client[,:]?\s+\*{0,2}' + NAME + r'\*{0,2}(?=\s+(?:is|are|has|seeks)\b|[,;\n]|$)', re.M),
    re.compile(r'^\*{0,2}' + NAME + r'\*{0,2}(?: in [A-Z][\w ,.-]{0,60}?)?\s+(?:is (?:the employer|hiring|looking for|seeking)|are hiring)\b[^\n]*', re.M),
    re.compile(r'^\*{0,2}About (?:[Tt]he )?[Cc]ompany\*{0,2}\s*\n+\*{0,2}' + NAME + r'\*{0,2}\s+(?:is|provides|develops|builds)\b[^\n]*', re.M),
]
GENERIC = {'we', 'our', 'the company', 'this company', 'the client', 'a company', 'you'}


# A company description alone is not client evidence; partner wording is explicit.
THIRD_PARTY = (
    r"\bour client\b[^.\n!?]{0,100}\b(?:hiring|seeking|looking for|seeks)\b"
    r"|\b(?:hiring|recruiting)\b[^.\n!?]{0,80}\bfor our clients?\b"
    r"|\b(?:hiring|seeking|looking for|recruiting)\b[^.\n!?]{0,80}\bfor one of our clients\b"
    r"|\b(?:direct employment|directly hiring) with our client\b"
    r"|\ba client of ours\b"
    r"|\bon behalf of (?:our|an?|one of our) (?:[\w,-]+ ){0,8}clients?\b"
    r"|\bon behalf of an? partner (?:company|organization|firm)\b"
)
INTERMEDIARY = re.compile(THIRD_PARTY, re.I)
# Keep the service adjacent to the provider verb; product subjects are checked below.
STAFFING_SERVICES = re.compile(
    r"\b(?:is|are) (?:an?|the) (?:(?:leading|global|international|specialist|specialized) ){0,3}"
    r"(?:staffing|recruiting|recruitment|talent(?: acquisition)?|placement) (?:agency|firm|company|consultancy)\b"
    r"|\b(?:is|are) a recruitment partner of this role\b"
    r"|\b(?:provider of|provid(?:e|es|ing)) "
    r"(?:staffing|recruiting|recruitment|talent(?: acquisition)?|(?:permanent )?placement)"
    r"(?: and (?:staffing|recruiting|recruitment))? services\b"
    r"|\b(?:provider of|provid(?:e|es|ing)) (?:innovative )?staffing solutions\b"
    r"|\bwe place candidates\b"
    r"|\bour (?:recruitment|recruiting|staffing) firm represents\b"
    r"|(?:היא |הינה )?חברת (?:השמה|גיוס)\b",
    re.I,
)
PRODUCT = re.compile(r"\b(?:software|platform|tool|saas|app|product)s?\b", re.I)
PLACEMENT_CONTEXT = re.compile(r"\b(?:clients?|candidates?|placement|placing|connecting (?:talented )?professionals)\b", re.I)


def _staffing_statement(text: str, company: str | None = None, *, allow_self: bool = True) -> bool:
    """Require a self or named-company subject, never a customer's business."""
    for clause in re.split(r'[.;!?]\s+|\n+', text):
        for match in STAFFING_SERVICES.finditer(clause):
            subject = clause[:match.start()].strip(' *\t')
            subject = re.sub(r'\s+(?:is|are)\s+(?:(?:an?|the|leading|global|international|specialist|specialized)\s*)*$', '', subject, flags=re.I)
            self_description = subject.casefold() in {'we', 'אנחנו', 'אנו'} or (
                not subject and match[0].casefold().startswith(('we ', 'our ')))
            named_company = bool(re.fullmatch(NAME, subject)) and not (
                subject.casefold().startswith(('our ', 'we ', 'the ', 'this ', 'an ', 'a '))
                or any(word[0].islower() and word not in {'of', 'the', 'and'} for word in subject.split()))
            if self_description and not allow_self:
                continue
            if not self_description and not named_company:
                continue
            if company is not None and not self_description and subject.casefold() != company.casefold():
                continue
            if PRODUCT.search(clause[:match.start()]) or re.match(r"\s*" + PRODUCT.pattern, clause[match.end():], re.I):
                continue
            if 'staffing solutions' in match[0].casefold() and not PLACEMENT_CONTEXT.search(clause):
                continue
            return True
    return False


ABOUT_HEADING = re.compile(
    r'^[ \t]*(?:\#{1,6}[ \t]+)?\*{0,2}'
    r'(?:About[ \t]+(?P<title>[^:\n*]+?)|אודות[ \t]+(?P<he_title>[^:\n*]+?)|(?P<he_us>אודותינו))'
    r'\*{0,2}[ \t]*(?::|$)', re.I | re.M)
SELF_HEADINGS = {'us', 'the company', 'company', 'החברה', 'אודותינו'}
# Unrecognized capitalized/brand or Hebrew words make ownership uncertain. This
# deliberately loses some agency labels rather than guessing a company's voice.
OWNER_PROSE = {
    'we', 'our', 'אנחנו', 'אנו', 'חברת', 'השמה', 'גיוס', 'היא', 'הינה',
    'אודות', 'החברה', 'אודותינו',
}
OWNER_TOKEN = re.compile(r"[^\W\d_][\w’'.&-]*")


def _heading_title(heading: re.Match) -> str:
    return next(value.strip().casefold() for value in heading.groups() if value)


def _uncertain_owner(text: str, publisher_names: set[str]) -> bool:
    text = ABOUT_HEADING.sub(
        lambda heading: '' if _heading_title(heading) in publisher_names | SELF_HEADINGS else heading[0], text)
    for name in sorted(publisher_names, key=len, reverse=True):
        text = re.sub(r'(?<!\w)' + re.escape(name) + r'(?!\w)', '', text, flags=re.I)
    text = re.sub(r'\bRole (?:responsibilities|details)\.', '', text)
    if re.search(r'\b(?:meet|our partner)\s+\w', text, re.I):
        return True
    return any(token.strip("’'.&-").casefold() not in OWNER_PROSE and (
        any(char.isupper() for char in token) or re.search(r'[\u0590-\u05ff]', token))
        for token in OWNER_TOKEN.findall(text))


def _publisher_staffing_statements(raw_jd: str, publisher: str):
    """Require an owner heading and uncontaminated context for first-person voice."""
    publisher_names = {publisher.casefold()}
    for name, aliases in ALIASES.items():
        if name.casefold() == publisher.casefold():
            publisher_names.update(alias.casefold() for alias in aliases)
    headings = list(ABOUT_HEADING.finditer(raw_jd))
    sections = [(None, 0, headings[0].start() if headings else len(raw_jd))]
    sections.extend((heading, heading.end(), headings[i + 1].start() if i + 1 < len(headings)
                     else len(raw_jd)) for i, heading in enumerate(headings))
    for heading, start, end in sections:
        title = _heading_title(heading) if heading else ''
        publisher_section = bool(heading) and title in publisher_names | SELF_HEADINGS
        publisher_section &= not _uncertain_owner(raw_jd[start:end], publisher_names)
        for line in re.compile(r'[^\n]+').finditer(raw_jd, start, end):
            line_start = raw_jd.rfind('\n', 0, line.start()) + 1
            preceding = '\n'.join(raw_jd[:line_start].splitlines()[-3:])
            allow_self = publisher_section and not _uncertain_owner(preceding, publisher_names)
            if _staffing_statement(line[0], publisher, allow_self=allow_self):
                yield line


ROLE_HEADING = re.compile(r'^\*{0,2}About (?:[Tt]he )?[Rr]ole\*{0,2}', re.M)


def resolve_employer(publisher: str, raw_jd: str, source: str) -> dict[str, object]:
    """Prefer role-linked names; absence of agency evidence never proves directness."""
    opening = '\n'.join(raw_jd.splitlines()[:32])[:2000]
    # Associate service descriptions with their own named company, not every role.
    staffing_about = {
        match['name'].strip(' .,').casefold(): match[0]
        for match in PATTERNS[3].finditer(opening)
        if _staffing_statement(match[0]) or INTERMEDIARY.search(match[0])
    }
    role_heading = ROLE_HEADING.search(opening)
    role_names: dict[str, tuple[str, str]] = {}
    blurb_names: dict[str, tuple[str, str]] = {}
    publisher_statements = list(_publisher_staffing_statements(raw_jd, publisher))
    publisher_statement = next(iter(publisher_statements), None)
    publisher_offsets = {hit.start() for hit in publisher_statements}
    agency_statement = next((line for line in re.finditer(r'[^\n]+', opening)
                             if INTERMEDIARY.search(line[0])
                             or line.start() in publisher_offsets), publisher_statement)
    if publisher_statement:
        staffing_about[publisher.casefold()] = publisher_statement[0]
    agency_evidence = agency_statement[0] if agency_statement else None
    intermediary_seen = agency_statement is not None
    role_intermediary_seen = bool(agency_statement and role_heading
                                  and agency_statement.start() > role_heading.start())
    for index, pattern in enumerate(PATTERNS):
        for match in pattern.finditer(opening):
            name = match['name'].strip(' .,')
            words = name.split()
            if (name.casefold().startswith(('our ', 'we ', 'the ', 'this ', 'an ', 'a '))
                    or name.casefold() in GENERIC
                    or any(word[0].islower() and word not in {'of', 'the', 'and'} for word in words)):
                continue
            is_blurb = index == 3 or (index == 2 and role_heading is not None
                                     and match.start() < role_heading.start())
            if (name.casefold() in STAFFING_KEYS
                    or name.casefold() in staffing_about
                    or (index >= 2 and INTERMEDIARY.search(match[0]))):
                agency_evidence = staffing_about.get(name.casefold(), match[0])
                intermediary_seen = True
                role_intermediary_seen |= not is_blurb
                continue
            if re.match(re.escape(publisher) + r"(?:\b|[’'])", name, re.I):
                name = publisher
            candidates = blurb_names if is_blurb else role_names
            candidates[name.casefold()] = (name, match[0])
    employer, evidence = None, None
    candidates = role_names if role_names or role_intermediary_seen else blurb_names
    if len(candidates) == 1:
        employer, evidence = next(iter(candidates.values()))
    elif not candidates and not intermediary_seen and source in ATS_SOURCES and publisher.casefold() not in PUBLISHER_KEYS:
        employer, evidence = publisher, f'source:{source}; company:{publisher}'
    relationship = ('unknown' if employer is None else
                    'unchanged' if employer.casefold() == publisher.casefold() else
                    'alias' if is_alias(publisher, employer) else 'resolved-different')
    return {'publisher': publisher, 'hiring_employer': employer,
            'employer_evidence': evidence, 'resolver_version': VERSION,
            'relationship': relationship, 'agency_evidence': agency_evidence}
