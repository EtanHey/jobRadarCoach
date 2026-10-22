"""Conservative attribution from source fields or quoted opening JD spans."""
from __future__ import annotations

import re

from scraper.ats_sources import ATS_SOURCES
from scraper.employer_publishers import PUBLISHERS
from scraper.employer_aliases import is_alias

VERSION = '4'
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


# Third-party wording excludes ordinary "join a company" and client SDK/team copy.
THIRD_PARTY = (
    r"\bour client(?=[:,.*]|\s+(?:is|are)\b|\s*$)"
    r"|\ba client of ours\b"
    r"|\bon behalf of (?:our|an?) (?:[\w,-]+ ){0,8}(?:client|company|organization|firm)\b"
)
INTERMEDIARY = re.compile(THIRD_PARTY, re.I)
# Service-provider framing, rather than product mentions of talent solutions.
STAFFING_SERVICES = re.compile(
    r"\bis an? (?:(?:leading|global|international|specialist|specialized) ){0,3}"
    r"(?:staffing|recruiting|recruitment|talent acquisition|placement) (?:agency|firm|company)\b"
    r"|\b(?:provider of|provid(?:e|es|ing)) (?:[\w-]+ ){0,3}"
    r"(?:staffing|recruiting|recruitment|talent(?: acquisition)?|(?:permanent )?placement)"
    r"(?: and (?:staffing|recruiting|recruitment))? services\b"
    r"|\b(?:provider of|provid(?:e|es|ing)) (?:[\w-]+ ){0,3}staffing solutions\b"
    r"|\bwe place candidates\b",
    re.I,
)
AGENCY_STATEMENT = re.compile(r'^.*(?:' + THIRD_PARTY + r')[^\n]*', re.I | re.M)
ROLE_HEADING = re.compile(r'^\*{0,2}About (?:[Tt]he )?[Rr]ole\*{0,2}', re.M)


def resolve_employer(publisher: str, raw_jd: str, source: str) -> dict[str, object]:
    """Prefer role-linked names; absence of agency evidence never proves directness."""
    opening = '\n'.join(raw_jd.splitlines()[:32])[:2000]
    # Associate service descriptions with their own named company, not every role.
    staffing_about = {
        match['name'].strip(' .,').casefold(): match[0]
        for match in PATTERNS[3].finditer(opening)
        if STAFFING_SERVICES.search(match[0]) or INTERMEDIARY.search(match[0])
    }
    role_heading = ROLE_HEADING.search(opening)
    role_names: dict[str, tuple[str, str]] = {}
    blurb_names: dict[str, tuple[str, str]] = {}
    agency_statement = AGENCY_STATEMENT.search(opening)
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
                    or re.search(r"\b(?:staffing|recruiting|recruitment)\b", name, re.I)
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
