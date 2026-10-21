"""Conservative attribution from source fields or quoted opening JD spans."""
from __future__ import annotations

import re

from scraper.ats_sources import ATS_SOURCES
from scraper.employer_publishers import PUBLISHERS

VERSION = '1'
PUBLISHER_KEYS = frozenset(p.casefold() for p in PUBLISHERS)
# Reviewed against all 57 family-2 evidence IDs; these are publishers, not clients.
NAME = r'(?P<name>[A-Z][\w·&.,’\'() \t-]{0,78}?)'
PATTERNS = [
    re.compile(r'^(?:Recruiting |Hiring |We are recruiting )?on behalf of\s+\*{0,2}' + NAME + r'\*{0,2}(?=\s+(?:for|is|are|we)\b|[,:;\n]|$)', re.M),
    re.compile(r'^(?:Our|our) client[,:]?\s+\*{0,2}' + NAME + r'\*{0,2}(?=\s+(?:is|are|has|seeks)\b|[,;\n]|$)', re.M),
    re.compile(r'^\*{0,2}' + NAME + r'\*{0,2}\s+(?:is (?:the employer|hiring|looking for|seeking)|are hiring)\b[^\n]*', re.M),
    re.compile(r'^\*{0,2}About (?:[Tt]he )?[Cc]ompany\*{0,2}\s*\n+\*{0,2}' + NAME + r'\*{0,2}\s+(?:is|provides|develops|builds)\b[^\n]*', re.M),
]
GENERIC = {'we', 'our', 'the company', 'this company', 'the client', 'a company', 'you'}


def resolve_employer(publisher: str, raw_jd: str, source: str) -> dict[str, object]:
    """Missing evidence stays unknown; a publisher's absence from the list proves nothing."""
    opening = '\n'.join(raw_jd.splitlines()[:32])[:2000]
    candidates: dict[str, tuple[str, str]] = {}
    for pattern in PATTERNS:
        for match in pattern.finditer(opening):
            name = match['name'].strip(' .,')
            words = name.split()
            if (name.casefold().startswith(('our ', 'we ', 'the ', 'this ', 'an ', 'a '))
                    or name.casefold() in GENERIC
                    or any(word[0].islower() and word not in {'of', 'the', 'and'} for word in words)
                    or name.casefold() in PUBLISHER_KEYS):
                continue
            if re.match(re.escape(publisher) + r"(?:\b|[’'])", name, re.I):
                name = publisher
            candidates[name.casefold()] = (name, match[0])
    employer, evidence = None, None
    if len(candidates) == 1:
        employer, evidence = next(iter(candidates.values()))
    elif not candidates and source in ATS_SOURCES and publisher.casefold() not in PUBLISHER_KEYS:
        employer, evidence = publisher, f'source:{source}; company:{publisher}'
    return {'publisher': publisher, 'hiring_employer': employer,
            'employer_evidence': evidence, 'resolver_version': VERSION}
