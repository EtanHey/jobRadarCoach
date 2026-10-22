"""Conservative role attribution; client prose vetoes inference, never badges."""
from __future__ import annotations

import re

from scraper.ats_sources import ATS_SOURCES
from scraper.employer_publishers import PUBLISHERS
from scraper.employer_aliases import is_alias
from scraper.geography import COUNTRY_CITY_ALIASES, COUNTRY_IDENTIFIERS, _normalized_location

VERSION = '17'
PUBLISHER_KEYS = frozenset(p.casefold() for p in PUBLISHERS)
# Reviewed staffing intermediaries whose names do not identify their business.
STAFFING_KEYS = PUBLISHER_KEYS | {'alldus'}
# Reviewed against all 57 family-2 evidence IDs; these are publishers, not clients.
NAME = r'(?P<name>[A-Z][\w·&.,’\'() \t-]{0,78}?)'
PATTERNS = [
    re.compile(r'^(?:Recruiting |Hiring |We are recruiting )?on behalf of\s+\*{0,2}' + NAME + r'\*{0,2}(?=\s+(?:for|is|are|we)\b|[,:;\n]|$)', re.M),
    re.compile(r'^(?:Our|our) client[,:]?\s+\*{0,2}' + NAME + r'\*{0,2}(?=\s+(?:is|are|has|seeks)\b|[,;\n]|$)', re.M),
    re.compile(r'^\*{0,2}' + NAME + r'\*{0,2}(?: in [A-Z][\w ,.-]{0,60}?)?\s+(?:is (?:the employer|hiring|looking for|seeking)|are hiring)\b[^\n]*', re.M),
    re.compile(r'^\*{0,2}About (?:[Tt]he )?[Cc]ompany\*{0,2}\s*\n+\*{0,2}' + NAME + r'\*{0,2}\s+(?:is|provides|develops|builds|היא|הינה)\b[^\n]*', re.M),
]
GENERIC = {'i', 'we', 'our', 'you', 'they', 'he', 'she', 'it', 'company', 'agency',
           'firm', 'recruiter', 'business', 'organization', 'team', 'client', 'publisher', 'employer',
           'the company', 'this company', 'the client', 'a company', 'אני', 'אנחנו', 'אנו'}
GENERIC_ORG_WORDS = frozenset('''data platform r d group hiring manager customer success engineering
    team department business unit networking ai role position remote fintech startup your next challenge idf veterans applicants in
    senior backend frontend engineer research development and of the
    צוות קבוצת קבוצה מחלקת מחלקה פלטפורמת פלטפורמה נתונים מחקר ופיתוח פיתוח מנהל מנהלת גיוס
    הצלחת לקוחות הנדסה תפקיד משרה מרחוק'''.split())
ENGLISH_ORG_HEADS = frozenset('''team teams department dept division unit squad crew chapter guild
    org organization function office desk'''.split())
HEBREW_ORG_HEAD = re.compile(r'[הובלמש]*(?:צוות|מחלקה|מחלקת|אגף|יחידה|יחידת|קבוצת|דסק)')
PLACE_NAMES = COUNTRY_IDENTIFIERS | {'ישראל'} | {
    _normalized_location(city) for cities in COUNTRY_CITY_ALIASES.values() for city in cities
}
GENERIC_SUBJECT = re.compile(r'^\*{0,2}' + NAME.replace('[A-Z]', '[A-Zא-ת]')
    + r'\*{0,2}\s+(?:is (?:hiring|looking for|seeking)|are hiring|מגייס(?:ת|ים|ות)?|מחפש(?:ת|ים|ות)?)\b', re.M)


def _generic_hiring_subject(name: str) -> bool:
    normalized = _normalized_location(name)
    words = normalized.split()
    if normalized in PLACE_NAMES or set(words) <= GENERIC_ORG_WORDS:
        return True
    # English heads come last; Hebrew construct heads come first, after prefixes.
    if words[-1] in ENGLISH_ORG_HEADS or HEBREW_ORG_HEAD.fullmatch(words[0]):
        return True
    return any(normalized.endswith(' ' + place)
               and set(normalized[:-len(place)].split()) <= GENERIC_ORG_WORDS
               for place in PLACE_NAMES)


# A company description alone is not client evidence; partner wording is explicit.
THIRD_PARTY = (
    r"\bour client\b[^.\n!?]{0,100}\b(?:hiring|seeking|looking for|seeks)\b"
    r"|\b(?:hiring|recruiting)\b[^.\n!?]{0,80}\bfor our clients?\b"
    r"|\b(?:hiring|seeking|looking for|recruiting)\b[^.\n!?]{0,80}\bfor one of our clients\b"
    r"|\b(?:direct employment|directly hiring) with our client\b"
    r"|\ba client of ours\b"
    r"|\bon behalf of (?:our|an?|one of our) (?:[\w,-]+ ){0,8}clients?\b"
    r"|\bon behalf of an? partner (?:company|organization|firm)\b"
    r"|(?:הלקוח שלנו|לקוח שלנו)\s+(?:מגייס|מחפש)"
    r"|(?:עבור|מטעם)\s+(?:הלקוח שלנו|לקוח שלנו|אחד מלקוחותינו)"
)
INTERMEDIARY = re.compile(THIRD_PARTY, re.I)
# Client wording can veto employer inference and nominate offline list reviews;
# it never supplies publisher agency evidence.
# Keep the service adjacent to the provider verb; product subjects are checked below.
STAFFING_BUSINESS = (
    r"\b(?:is|are) (?:an?|the) (?:(?:leading|global|international|specialist|specialized) ){0,3}"
    r"(?:staffing|recruiting|recruitment|talent(?: acquisition)?|placement) (?:agency|firm|company|consultancy)\b"
)
STAFFING_SERVICES = re.compile(
    STAFFING_BUSINESS
    + r"(?=\s*(?:[.,;!?]|$)|\s+(?:that|which|specializing|connecting|helping)\b)"
    r"|\b(?:is|are) a recruitment partner of this role\b"
    r"|\b(?:provider of|provid(?:e|es|ing)) "
    r"(?:staffing|recruiting|recruitment|talent(?: acquisition)?|(?:permanent )?placement)"
    r"(?: and (?:staffing|recruiting|recruitment))? services\b"
    r"|\b(?:provider of|provid(?:e|es|ing)) (?:innovative )?staffing solutions\b"
    r"|(?:היא |הינה )?חברת (?:השמה|גיוס)\b"
    r"(?=\s*(?:[.,;!?]|$)|\s+(?:אשר|המתמחה|מתמחה|המחברת|מחברת|המסייעת|מסייעת|שמתמחה|שמחברת|שמסייעת|שעוזרת)\b)",
    re.I,
)
STAFFING_DESCRIPTIONS = re.compile(
    STAFFING_BUSINESS + r"(?=\s|[.,;!?]|$)|" + STAFFING_SERVICES.pattern
    + r"|(?:היא |הינה )?חברת (?:השמה|גיוס)\b(?=\s|[.,;!?]|$)", re.I)
PRODUCT = re.compile(r"\b(?:software|platform|tool|saas|app|product)s?\b", re.I)
PLACEMENT_CONTEXT = re.compile(r"\b(?:clients?|candidates?|placement|placing|connecting (?:talented )?professionals)\b", re.I)


def _staffing_statement(text: str, company: str, *, require_complete: bool = True) -> bool:
    """Require a named-company subject; first-person ownership is never inferred."""
    predicates = STAFFING_SERVICES if require_complete else STAFFING_DESCRIPTIONS
    for clause in re.split(r'[.;!?]\s+|\n+', text):
        for match in predicates.finditer(clause):
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

# Eligibility is structural: unfamiliar headings never grant publisher voice.
JOB_HEADING = re.compile(
    r'^(?:about (?:the )?role|job description|the position|responsibilities|תיאור המשרה|על התפקיד)\s*:?$', re.I)
QUOTE_CHARACTERS = re.compile('[\'"‘’“”«»„‟‚‛״׳‹›`❛❜❝❞]')
SIGNATURE = re.compile(r"\s[—–-]\s+[^\W\d_][\w’'-]*(?:[ \t]+[^\W\d_][\w’'-]*)*(?:,[^\r\n]*)?[.!]?\s*$")


def _first_party_text(raw_jd: str, attributable: str) -> str:
    """Keep only opening/first-job paragraphs, preserving raw evidence offsets."""
    eligible, paragraph_started = True, False
    lines = []
    offset = 0
    for line in raw_jd.splitlines(keepends=True):
        text = line.strip()
        heading = text.strip('#* _').strip()
        job_heading = JOB_HEADING.fullmatch(heading)
        predicate = re.search(r'\b(?:is|are|we|provides|builds|hiring|seeking)\b|מגייס|מחפש', heading, re.I)
        # Plain headings have no sentence punctuation or predicate. Markdown
        # headings are explicit, including unfamiliar headings in other languages.
        heading_like = (text.startswith('#') or
                        (re.fullmatch(r'(?:\*\*|__|\*|_)(.+?)(?:\*\*|__|\*|_)', text)
                         and not predicate) or
                        (re.fullmatch(r'[\w &:/()–—-]+', heading)
                         and not predicate))
        if job_heading or heading_like:
            eligible, paragraph_started = bool(job_heading), False
            allowed = False
        elif not text:
            if paragraph_started:
                eligible = False
            allowed = False
        else:
            paragraph_started = True
            allowed = eligible and not QUOTE_CHARACTERS.search(line) and not SIGNATURE.search(line)
        segment = attributable[offset:offset + len(line)]
        lines.append(segment if allowed else re.sub(r'[^\r\n]', ' ', segment))
        offset += len(line)
    return ''.join(lines)


def resolve_employer(publisher: str, raw_jd: str, source: str) -> dict[str, object]:
    """Prefer role-linked names; absence of agency evidence never proves directness."""
    attributable = _attributable_text(raw_jd)
    first_party = _first_party_text(raw_jd, attributable)
    opening = ''.join(attributable.splitlines(keepends=True)[:32])[:2000]

    def raw_evidence(match: re.Match) -> str:
        return raw_jd[match.start():min(match.end(), match.start() + 2000)]

    # Associate service descriptions with their own named company, not every role.
    staffing_about = {
        match['name'].strip(' .,').casefold()
        for match in PATTERNS[3].finditer(opening)
        if _staffing_statement(match[0], match['name'].strip(' .,'), require_complete=False)
    }
    role_heading = ROLE_HEADING.search(opening)
    role_names: dict[str, tuple[str, str]] = {}
    blurb_names: dict[str, tuple[str, str]] = {}
    publisher_statement = next(_publisher_staffing_statements(attributable, publisher), None)
    # Only a statement about this publisher can supply free-text badge evidence.
    if _staffing_statement(attributable, publisher, require_complete=False):
        staffing_about.add(publisher.casefold())
    agency_evidence = raw_evidence(publisher_statement) if publisher_statement else None
    publisher_is_agency = publisher_statement is not None or publisher.casefold() in PUBLISHER_KEYS
    client_wording_seen = bool(INTERMEDIARY.search(raw_jd))
    staffing_candidate_seen = publisher.casefold() in staffing_about
    role_intermediary_seen = bool(publisher_statement and role_heading
                                  and publisher_statement.start() > role_heading.start())
    # Hebrew subjects are recognized only for this veto, not new attribution.
    generic_subject_seen = any(_generic_hiring_subject(match['name'])
                               for match in GENERIC_SUBJECT.finditer(opening))
    for index, pattern in enumerate(PATTERNS):
        for match in pattern.finditer(opening):
            if index < 2 and not first_party[match.start():match.end()].strip():
                continue
            name = match['name'].strip(' .,')
            if index == 2 and _generic_hiring_subject(name):
                generic_subject_seen = True
                continue
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
                # A recruiter description excludes that company as the employer;
                # it says nothing about the publisher's own staffing business.
                staffing_candidate_seen = True
                role_intermediary_seen |= not is_blurb
                continue
            suffix = name[len(publisher):] if name.casefold().startswith(publisher.casefold()) else None
            if suffix is not None and (not suffix or re.match(r"['’]s(?:\s|$)", suffix)
                                       or (re.match(r'\W', suffix)
                                           and _generic_hiring_subject(suffix.strip(' ()')))):
                name = publisher
            candidates = blurb_names if is_blurb else role_names
            candidates[name.casefold()] = (name, raw_evidence(match))
    employer, evidence = None, None
    candidates = (role_names if role_names or role_intermediary_seen or client_wording_seen or generic_subject_seen
                  else blurb_names)
    if len(candidates) == 1:
        employer, evidence = next(iter(candidates.values()))
    elif (not candidates and not publisher_is_agency and not staffing_candidate_seen
          and not client_wording_seen and not generic_subject_seen
          and source in ATS_SOURCES):
        employer, evidence = publisher, f'source:{source}; company:{publisher}'
    relationship = ('unknown' if employer is None else
                    'unchanged' if employer.casefold() == publisher.casefold() else
                    'alias' if is_alias(publisher, employer) else 'resolved-different')
    return {'publisher': publisher, 'hiring_employer': employer,
            'employer_evidence': evidence, 'resolver_version': VERSION,
            'relationship': relationship, 'agency_evidence': agency_evidence}
