"""Conservative role attribution using named staffing and explicit client evidence."""
from __future__ import annotations

import re

from scraper.ats_sources import ATS_SOURCES
from scraper.employer_publishers import PUBLISHERS
from scraper.employer_aliases import is_alias

VERSION = '11'
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
GENERIC = {'i', 'we', 'our', 'you', 'they', 'he', 'she', 'it', 'company', 'agency',
           'firm', 'recruiter', 'business', 'organization', 'team', 'client', 'publisher', 'employer',
           'the company', 'this company', 'the client', 'a company', 'אני', 'אנחנו', 'אנו'}


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
    r"|(?:היא |הינה )?חברת (?:השמה|גיוס)\b",
    re.I,
)
PRODUCT = re.compile(r"\b(?:software|platform|tool|saas|app|product)s?\b", re.I)
PLACEMENT_CONTEXT = re.compile(r"\b(?:clients?|candidates?|placement|placing|connecting (?:talented )?professionals)\b", re.I)


def _staffing_statement(text: str, company: str) -> bool:
    """Require a named-company subject; first-person ownership is never inferred."""
    for clause in re.split(r'[.;!?]\s+|\n+', text):
        for match in STAFFING_SERVICES.finditer(clause):
            subject = clause[:match.start()].strip(' *\t')
            subject = re.sub(r'\s+(?:is|are)\s+(?:(?:an?|the|leading|global|international|specialist|specialized)\s*)*$', '', subject, flags=re.I)
            if subject.casefold() in GENERIC:
                continue
            if subject.casefold() != company.casefold() and not is_alias(company, subject):
                continue
            if PRODUCT.search(clause[:match.start()]) or re.match(r"\s*" + PRODUCT.pattern, clause[match.end():], re.I):
                continue
            if 'staffing solutions' in match[0].casefold() and not PLACEMENT_CONTEXT.search(clause):
                continue
            return True
    return False


# Preserve offsets so persisted evidence remains a verbatim slice of the raw JD.
QUOTED = re.compile(r'"[^"]*"|“[^”]*”|«[^»]*»|(?<!\w)\'[^\']*\'(?!\w)')
ATTRIBUTED = re.compile(
    r"(?i:\b(?:says|said|testimonials?)\b|\breviews?(?:\s*:|\s+(?:by|from)\b)"
    r"|\b(?:a|this|the) review\b|\b\w+[’']s review\b)"
    r"|[—–][ \t]+[^\W\d_][\w’'-]*(?:[ \t]+[^\W\d_][\w’'-]*){0,3},[ \t]+"
    r"(?i:head|director|ceo|cto|vp|manager|recruiter|founder|engineer|talent|מנהלת?|מגייסת?)\b[^.\n]{0,80}\s*$"
    r"|[—–][ \t]+(?!(?i:remote|hybrid|on[- ]?site|full[- ]?time|part[- ]?time)\b)"
    r"[A-Z][\w’'-]*(?:[ \t]+[A-Z][\w’'-]*){0,3}[.!]?\s*$")
TESTIMONIAL_HEADING = re.compile(
    r'^(?:(?:customer )?testimonials?|(?:customer )?reviews?|what our customers say|ממליצים|המלצות)(?:\s*:\s*.*|\s*)$', re.I)
SECTION_HEADING = re.compile(
    r'^(?:about|responsibilities|requirements|qualifications|benefits|job (?:description|details|requirements|responsibilities)|אודות)\b', re.I)
CUSTOMER_HEADING = re.compile(r'\b(?:testimonials?|reviews?|customers?|stories)\b|ממליצים|המלצות', re.I)


def _attributable_text(raw_jd: str) -> str:
    """Exclude other speakers before any agency or employer-name extraction."""
    def blank(text: str) -> str:
        return re.sub(r'[^\r\n]', ' ', text)

    # Mask quotes before attribution lines, including quotes spanning those lines.
    unquoted = QUOTED.sub(lambda match: blank(match[0]), raw_jd)
    lines = []
    testimonial = False
    offset = 0
    for line in raw_jd.splitlines(keepends=True):
        heading = line.strip().strip('#* ').strip()
        if TESTIMONIAL_HEADING.fullmatch(heading):
            testimonial = True
        elif SECTION_HEADING.match(heading) and not CUSTOMER_HEADING.search(heading):
            testimonial = False
        excluded = testimonial or line.lstrip().startswith('>') or ATTRIBUTED.search(line)
        lines.append(blank(line) if excluded else unquoted[offset:offset + len(line)])
        offset += len(line)
    return ''.join(lines)


def _publisher_staffing_statements(raw_jd: str, publisher: str):
    """Named third-person publisher statements count at any position in the JD."""
    for line in re.finditer(r'[^\n]+', raw_jd):
        if _staffing_statement(line[0], publisher):
            yield line


ROLE_HEADING = re.compile(r'^\*{0,2}About (?:[Tt]he )?[Rr]ole\*{0,2}', re.M)


def resolve_employer(publisher: str, raw_jd: str, source: str) -> dict[str, object]:
    """Prefer role-linked names; absence of agency evidence never proves directness."""
    attributable = _attributable_text(raw_jd)
    opening = ''.join(attributable.splitlines(keepends=True)[:32])[:2000]

    def raw_evidence(match: re.Match) -> str:
        return raw_jd[match.start():match.end()]

    # Associate service descriptions with their own named company, not every role.
    staffing_about = {
        match['name'].strip(' .,').casefold(): raw_evidence(match)
        for match in PATTERNS[3].finditer(opening)
        if _staffing_statement(match[0], match['name'].strip(' .,')) or INTERMEDIARY.search(match[0])
    }
    role_heading = ROLE_HEADING.search(opening)
    role_names: dict[str, tuple[str, str]] = {}
    blurb_names: dict[str, tuple[str, str]] = {}
    publisher_statements = list(_publisher_staffing_statements(attributable, publisher))
    publisher_statement = next(iter(publisher_statements), None)
    publisher_offsets = {hit.start() for hit in publisher_statements}
    agency_statement = next((line for line in re.finditer(r'[^\n]+', opening)
                             if INTERMEDIARY.search(line[0])
                             or line.start() in publisher_offsets), publisher_statement)
    if publisher_statement:
        staffing_about[publisher.casefold()] = raw_evidence(publisher_statement)
    agency_evidence = raw_evidence(agency_statement) if agency_statement else None
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
                agency_evidence = staffing_about.get(name.casefold(), raw_evidence(match))
                intermediary_seen = True
                role_intermediary_seen |= not is_blurb
                continue
            if re.match(re.escape(publisher) + r"(?:\b|[’'])", name, re.I):
                name = publisher
            candidates = blurb_names if is_blurb else role_names
            candidates[name.casefold()] = (name, raw_evidence(match))
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
