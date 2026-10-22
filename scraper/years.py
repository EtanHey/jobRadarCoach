"""Conservative Hebrew applicant-year frames; no model or I/O."""

import re

NUMBER_WORDS = "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen twenty".split()


def normalize_english_years(text: str) -> str:
    """Normalize only closed number tokens before a year unit or range connector."""
    return re.sub(r"\b(?:" + "|".join(NUMBER_WORDS) + r")\b(?=\s*(?:years?\b|[-–—]|to\b))",
                  lambda match: str(NUMBER_WORDS.index(match[0].lower())), text, flags=re.I)


HEBREW_YEARS = re.compile(
    r"(?<![\w.])(?:(?:לפחות|מינימום(?: של)?)\s+)?"
    r"(?P<minimum>[0-9]{1,2})(?:\s*(?:[-–—]|עד)\s*(?P<maximum>[0-9]{1,2}))?\+?\s+שנות\s+נ[י]?סיון(?![א-ת])"
    r"|(?<![\w.])נ[י]?סיון\s+של\s+(?:לפחות\s+)?"
    r"(?P<after>[0-9]{1,2})(?:\s*(?:[-–—]|עד)\s*(?P<after_max>[0-9]{1,2}))?\+?\s+שנים(?![א-ת])"
)
PREFIX = re.compile(r"^[^A-Za-zא-ת]*(?:(?:דרישות(?: התפקיד)?|נדרש(?:ת)?(?: נ[י]?סיון)?)[ :\t]*)?$")
REJECT = re.compile(r"(?:^|[^א-ת])(?:לא|ללא|עד|יתרון|אינן חובה|אינו חובה|אין חובה|או)(?![א-ת])")


def blocking_hebrew_years(text: str) -> bool:
    for match in HEBREW_YEARS.finditer(text):
        minimum = int(match['minimum'] or match['after'])
        maximum = match['maximum'] or match['after_max']
        if minimum < 7 or (maximum is not None and int(maximum) < minimum):
            continue
        before = text[:match.start()]
        prefix = re.split(r"[.!?\n]", before)[-1].strip()
        if not PREFIX.fullmatch(prefix):
            continue
        suffix = re.split(r"[.!?;]|\n(?![ \t]+(?:או)(?=\s))", text[match.end():], maxsplit=1)[0]
        if REJECT.search(prefix + ' ' + suffix):
            continue
        section = None
        for line in before.splitlines():
            heading = re.sub(r"^[^A-Za-zא-ת]+|[:*#]+$", "", line).strip()
            if re.fullmatch(r"דרישות(?: התפקיד)?|מה אנחנו מחפשים\??", heading):
                section = 'required'
            elif re.fullmatch(r"יתרונות|יתרון|preferred(?: qualifications?)?|nice to have|bonus|advantages?", heading, re.I):
                section = 'optional'
            elif re.match(r"#{1,6}\s", line):
                section = None
        if section == 'optional':
            continue
        if section == 'required' or re.search(r"לפחות|מינימום|נדרש|דרישות", prefix + match[0]):
            return True
    return False
