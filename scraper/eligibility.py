"""Precision-first local eligibility: unreadable restrictions veto every pass."""

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
import re
from typing import Literal, TypedDict

from scraper.geography import (
    _normalized_location,
    has_geographic_context,
    match_geographic_place,
    normalize_israeli_location,
)


class Eligibility(TypedDict):
    eligibility: Literal["eligible", "blocked", "unknown"]
    eligibility_reason: str


CLAUSES = re.compile(
    r"[;\n]|(?<!\bu\.s)(?<!\bu\.s\.a)(?<!\be\.g)(?<!\bincl)(?<=[a-z])\.\s+", re.I
)
CENTRAL = re.compile(
    r"\b(?:central|cent(?:er|re)(?: of (?:the country|israel))?|gush dan)\b|מרכז", re.I
)
OFFICE = re.compile(
    r"\b(?:on[ -]?site|office[ -]based|hybrid)(?![ /-]+(?:cloud|mobile|apps|infrastructure|"
    r"edge|environments?|SSR|multi[ -]region|data|networks?|funds|retrieval|Mamba)\b)\b|"
    r"היברידי(?:ת)?|(?:עבודה|המשרה)\s+במשרד",
    re.I,
)
RESIDENCE = re.compile(
    r"\b(?:(?:must|should|need to|required to)\s+(?:already\s+)?(?:be\s+)?"
    r"(?:reside|live|based|located)\s+in|(?:must|need to|required to)\s+relocate\s+to|"
    r"only\s+(?:candidates|applicants)\s+(?:based|located)\s+in|"
    r"(?:be\s+)?based\s+in|(?:only\s+)?residents?\s+of)\s+|"
    r"(?:חובה|נדרש)\s+(?:להתגורר|לגור)\s+ב|ל?תושבי\s+",
    re.I,
)
EXCLUSION = re.compile(
    r"\b(?:(?:except|excluding|not open to|not available (?:in|from))\s+"
    r"(?:(?:applicants|candidates)\s+(?:from|in)\s+)?|excluded countries\s*:\s*)",
    re.I,
)
ISRAEL_EXCLUDED = re.compile(
    r"\b(?:israel|israelis)\s+(?:(?:is|are)\s+)?"
    r"(?:excluded|not (?:allowed|eligible|an available work location))\b|"
    r"\bnot open to\s+(?:israelis|israeli (?:applicants|candidates))\b|"
    r"(?<!\w)לא כולל ישראל(?!\w)",
    re.I,
)
REMOTE = re.compile(r"\bremot(?:e|ely)\b|(?:עבודה\s+)?מרחוק", re.I)
ATTENDANCE = re.compile(
    r"\b(?:(?:this\s+(?:role|position|job)\s+)?requires?\s+)?"
    r"(?:\d+|one|two|three|four|five)\s+days?\s*"
    r"(?:/\s*week|(?:each|per|a)\s+week)\s+in\s+(?:our\s+|the\s+)?",
    re.I,
)
REQUIRED_OFFICE = re.compile(
    r"\b(?:requires?|must|need to|required to)\s+"
    r"(?:(?:work|working|attendance|attend|be|present|physically|regularly|to)\s+)*"
    r"(?:in|at)\s+(?:our\s+|the\s+)",
    re.I,
)
OTHER_ROLES = re.compile(
    r"\b(?:(?:some|other)\s+roles?|"
    r"(?:the|our)\s+\w+\s+team\b)",
    re.I,
)
PERMISSION = re.compile(
    r"\bopen to (?:candidates|applicants) (?:in|from)\s+|"
    r"ניתן לעבוד מכל מקום ב",
    re.I,
)
# A recognized rule must account for every restriction span. Unsupported grammar,
# unknown places, citizenship, work authorization and time zones remain unknown.
RESTRICTION = re.compile(
    r"\b(?:must|should|need to|required|requires?|mandatory|only|based in|reside|residents?|located in|live in|"
    r"relocate|residence|residency|not (?:open|accepting|available|eligible)|except|excluding|eligible to work|citizens?(?:hip)?|"
    r"work authorization|time[ -]?zone|attendance|attend)\b|"
    r"\bdays?\s*(?:/\s*week|(?:each|per|a)\s+week)\b|"
    r"(?<!\w)(?:חובה|נדרש(?:ת|ים|ות)?|אזרחות|להתגורר|לגור|מגורים|תושבי\w*|רק|בלבד|למעט|פרט ל|לא)(?!\w)",
    re.I,
)
NEGATION = re.compile(
    r"\b(?:no need to|not (?:required|necessary) to)\s+(?:reside|live|be based|relocate)\s+(?:in|to)\s+|"
    r"\bnot\s+(?:remote|on[ -]?site|office[ -]based|hybrid)\b",
    re.I,
)
ATTRIBUTE_REQUIREMENT = (
    r"\s+(?:must|should|needs?\s+to|(?:is\s+)?required|only|mandatory|"
    r"(?:[\w׳״'-]+\s+)?(?:חובה|נדרש(?:ת|ים|ות)?))(?!\w)"
)
# Match bounded policy phrases, never their containing clause. Anything after
# the phrase still goes through the same geographic restriction parser.
NON_LOCATION_POLICY = re.compile(
    r"\b(?:equal (?:employment )?opportunit\w*(?: employer)?|"
    r"(?:salary range|annual (?:base )?salary)\s+is\s+only applicable to\s+"
    r"(?:U\.S\.|US|United States)[ -]based candidates|"
    r"on[ -]?site (?:courses|wellness(?: centers)?|caf[ée])|"
    r"accommodations?|protected (?:personal )?characteristics|"
    r"privacy (?:act|policy)|GDPR|salary range|annual (?:base )?salary|"
    r"benefits (?:program|in this paragraph)|(?:office|on[ -]?site) perks|"
    r"recruiters (?:correspond|only contact)|legitimate communication|"
    r"employment decisions|notify all applicants of their rights)\b",
    re.I,
)

# Lists stop before a requirement's subject. Atomic attributes prevent falling
# back from 'citizenship status must' to the shorter 'citizenship'.
PROTECTED_ATTRIBUTE = (
    r"race|colou?r|national origin|nationality|citizenship(?: status)?|immigration status|residency status|"
    r"ancestry|religion|creed|sex|sexual orientation|gender(?: identity| expression)?|"
    r"age|disability|veteran(?: or military)? status|military status|marital status|"
    r"pregnancy|disabled veteran|status as a protected veteran|Veteran status|"
    r"מין|גזע|דת|לאום|אזרחות|מעמד הגירה|גיל|מוגבלות"
)
EEO_LIST = re.compile(
    rf"(?:\b(?:without regard to|regardless of)\b|בלי קשר ל|ללא הבדל)\s*"
    rf"(?>(?>(?:{PROTECTED_ATTRIBUTE})(?!\w))(?!{ATTRIBUTE_REQUIREMENT})"
    rf"(?:\s*(?:,\s*(?:(?:and|or)\s+)?|\s+(?:and|or)\s+|\s+או\s+|\s+ו)"
    rf"(?>(?:{PROTECTED_ATTRIBUTE})(?!\w))(?!{ATTRIBUTE_REQUIREMENT}))*)"
    rf"(?!\s+(?:and|or)\s+(?:{PROTECTED_ATTRIBUTE})(?!\w){ATTRIBUTE_REQUIREMENT})",
    re.I,
)
TEAM_CITIZENS = re.compile(
    r"(\bour team is made up of\b[^.;\n]*?)(\bdual citizens\b)"
    r"(?!\s+(?:only|required|must|may apply)\b)",
    re.I,
)
APPLICANT = (
    r"(?:applicants?|candidates?|residents?|citizens?|"
    r"[לוהש]*מועמד(?:ים|ות|ת)?|[לוהש]*תושב(?:י|ים|ות)?|[לוהש]*אזרח(?:י|ים|יות|ית)?)"
)
SLOT = r"[^;.!?\n]+?"
APPLICANT_FRAMES = tuple(
    re.compile(pattern, re.I)
    for pattern in (
        rf"(?<!\w){APPLICANT}\s+(?P<slot>{SLOT})\s+(?:only\b|בלבד(?!\w))",
        rf"(?<!\w)(?:only|[והש]*רק)\s+{APPLICANT}\s+(?P<slot>{SLOT})(?=$|[.!?]|\s+(?:may|can|are eligible|רשאים)\b)",
        rf"(?<!\w)(?:only|[והש]*רק)\s+(?P<slot>{SLOT})\s+{APPLICANT}(?!\w)",
        rf"(?<!\w)(?P<slot>[\w׳״'-]+(?:\s+[\w׳״'-]+)*)\s+{APPLICANT}\s+(?:only\b|בלבד(?!\w))",
    )
)
LOCATION_FRAME = re.compile(
    r"(?<!\w)(?:(?:must|required to)\s+(?:live|reside|relocate|work)\s+(?:in|to)\s+|"
    r"[והש]*(?:חובה|נדרש(?:ת|ים|ות)?)\s+(?:לגור|להתגורר|לעבור|לעבוד|רילוקיישן)\s+(?:רק\s+)?[בל])"
    rf"(?P<slot>{SLOT})(?=$|[.!?])",
    re.I,
)
CREDENTIAL = re.compile(
    r"\b(?:passports?|work permits?|work authori[sz]ation|visas?|citizenship)\b|"
    r"(?<!\w)[בלמהוש]*(?:דרכון|אישור עבודה|ויזה|אזרחות)(?!\w)",
    re.I,
)
NATIONALITY_CREDENTIAL = re.compile(
    r"\b(?:nationality|national origin|immigration status|residency status)\b",
    re.I,
)
LANGUAGE_SKILL = re.compile(
    r"\b[\w׳״']+(?:[- ]speaking|\s+speakers?)\b|"
    r"\b(?:speaks?|speaking|fluent(?:\s+in)?|native|proficiency(?:\s+in)?|language)\s+[\w׳״']+|"
    r"(?<!\w)(?:לדבר|דובר(?:/ת|י|ת|ים|ות)?|שפה|ברמת שפת אם)\s+(?:שפה\s+)?[\w׳״']+",
    re.I,
)
OWN_COUNTRY_AUTHORIZATION = re.compile(
    r"\b(?:applicants?|candidates?)\s+must\s+(?:"
    r"have the legal right to work in the country where the (?:position|role|job) is based"
    r"(?:,?\s+without the need for visa sponsorship)?|"
    r"be authorized to work in the country in which they apply"
    r"(?: and will be required to provide proof of employment eligibility as a condition of hire)?)\b|"
    r"(?<!\w)(?:על המועמדים להיות|המועמדים (?:נדרשים|חייבים) להיות)\s+"
    r"(?:בעלי זכות חוקית לעבוד|רשאים לעבוד כחוק|בעלי אישור עבודה)\s+"
    r"במדינה (?:שבה|בה) (?:המשרה (?:ממוקמת|מבוססת)|ממוקמת המשרה)"
    r"(?:,? ללא צורך בחסות ל(?:וויזה|ויזה))?(?!\w)",
    re.I,
)
OWN_ATTENDANCE = re.compile(
    r"\b(?:\d+|one|two|three|four|five)\s+days?\s*"
    r"(?:(?:/\s*week|(?:each|per|a)\s+week)\s+)?"
    r"(?:working\s+)?(?:in[ -]|from\s+|at\s+)(?:(?:our|the)\s+)?office\b",
    re.I,
)


# These are complete tokens/phrases, never accepted continuation prefixes.
OWN_WORK_MODEL = re.compile(
    r"(?<!\w)(?:hybrid|remote|on[ -]?site|in[ -]office|office[ -]based|office|"
    r"flexible|model|schedule|environment|policy|work|working|"
    r"(?:\d+|one|two|three|four|five)\s+days?|per\s+week|a\s+week|each\s+week|weekly|"
    r"from\s+home|WFH|option|"
    r"a|an|the|and|or|with|in|at|from|our|we|is|"
    r"[והב]*(?:היברידי(?:ת)?|מרחוק|משרד|גמיש(?:ה)?|מודל|מתכונת|סביבת|סביבה|"
    r"מדיניות|עבודה|עובדים|שבועי(?:ת)?|אפשרות)|"
    r"(?:\d+|יום אחד|יומיים|שני|שלושה|שלוש|ארבעה|ארבע|חמישה|חמש)\s*(?:ימים)?|"
    r"בשבוע|מהבית|שלנו|אנחנו|עם|או|ו)(?!\w)",
    re.I,
)
OWN_SITE = re.compile(
    r"\b(?:(?:(?:our|the|this)\s+)?(?:company|office|site|role|position|job)\s+(?:is\s+)?)?"
    r"(?:based|located)\s+in\s+|"
    r"(?<!\w)(?:החברה|המשרד|המשרה)\s+(?:ממוקמת|ממוקם|מבוססת)\s+ב",
    re.I,
)


def _own_workplace_terms(
    clause: str, *, attendance: bool, own_location: str
) -> str | None:
    """Consume a whole local workplace clause; None retains an unresolved rule."""
    authorization = OWN_COUNTRY_AUTHORIZATION.search(clause)
    site = OWN_SITE.search(clause)
    workplace = (
        OFFICE.search(clause) or OWN_ATTENDANCE.search(clause)
        or re.search(r"\bin[ -]office\b", clause, re.I)
    )
    if not (workplace or authorization or site):
        return clause
    if workplace and not attendance:
        return clause

    # Recognize pronouns before removing places, so deletion cannot create a
    # new 'with us' phrase out of 'with Tel Aviv us'.
    remainder = re.sub(r"\b(?:join|with)\s+us\b", " ", clause, flags=re.I)
    remainder = OWN_COUNTRY_AUTHORIZATION.sub(" ", remainder)
    remainder = OWN_SITE.sub(" ", remainder)
    # Only places actually present in the resolved ATS field can be inherited.
    # Normalize separators, but never drop an unfamiliar token or short code.
    places = {_normalized_location(own_location)}
    for part in re.split(r"[,;()]|\s+and\s+", own_location, flags=re.I):
        if part.strip():
            places.add(_normalized_location(part))
    remainder = _normalized_location(normalize_israeli_location(remainder))
    own_place_consumed = False
    for place in sorted(places, key=len, reverse=True):
        if place:
            remainder, count = re.subn(
                r"(?<!\w)(?:[במל])?" + re.escape(place) + r"(?!\w)",
                " ", remainder,
            )
            own_place_consumed |= bool(count)
    if site and not own_place_consumed:
        return None
    remainder = OWN_WORK_MODEL.sub(" ", remainder)
    return None if remainder.strip() else " "


def _without_policy(text: str) -> str:
    text = EEO_LIST.sub(" ", text)
    text = TEAM_CITIZENS.sub(r"\1 ", text)
    return NON_LOCATION_POLICY.sub(" ", text)


def _qualified_credential(text: str) -> bool:
    for credential in NATIONALITY_CREDENTIAL.finditer(text):
        # These attributes are also ordinary EEO-list entries. Require an
        # adjacent obligation, rather than treating every mention as a rule.
        if re.match(ATTRIBUTE_REQUIREMENT, text[credential.end() :], re.I) or re.search(
            r"(?<!\w)(?:must|should|needs?\s+to|required|only|mandatory|חובה|נדרש(?:ת|ים|ות)?)"
            r"\s+(?:(?:have|hold|be|of|a|an|the)\s+)*(?:[\w׳״'-]+\s+)?$",
            text[: credential.start()],
            re.I,
        ):
            return True
    for credential in CREDENTIAL.finditer(text):
        if re.match(
            r"\s+(?:for|of|in|from)\s+(?:the\s+)?"
            r"(?!(?:this|our|your|their|position|role|job)\b)\S+",
            text[credential.end() :],
            re.I,
        ):
            return True
        before = re.search(r"[\w׳״'-]+\s*$", text[: credential.start()])
        after = re.match(r"\s+([\w׳״'-]+)", text[credential.end() :])
        qualifiers = [
            before.group().strip() if before else "",
            after[1] if after else "",
        ]
        if any(
            q.casefold()
            not in {
                "",
                "a",
                "an",
                "the",
                "any",
                "our",
                "your",
                "their",
                "valid",
                "current",
                "work",
                "for",
                "of",
                "is",
                "are",
                "required",
                "mandatory",
                "only",
                "hold",
                "have",
                "obtain",
                "sponsor",
                "applicants",
                "must",
                "and",
                "or",
                "not",
                "to",
                "with",
            }
            for q in qualifiers
        ):
            return True
    return False


def _is_israeli_slot(slot: str) -> bool:
    # Only Israeli demonyms are needed: every other adjective stays unresolved.
    slot = re.sub(
        r"^(?:from|in|of|based in|located in)\s+", "", slot.strip(), flags=re.I
    )
    slot = re.sub(
        r"(?<!\w)(?:Israeli|ישראלי(?:ם|ות|ת)?)(?!\w)", "Israel", slot, flags=re.I
    )
    scope = _scope(slot, 0)
    return (
        scope.complete
        and bool(scope.kinds)
        and all(kind in {"israel", "noncentral"} for kind in scope.kinds)
        and not slot[scope.end :].strip(" .)")
    )


def _clauses(source: str) -> Iterator[str]:
    for original in CLAUSES.split(source):
        contrast = re.search(r"\b(?:but|however|while)\b", original, re.I)
        if contrast and NON_LOCATION_POLICY.search(original[: contrast.start()]):
            # Split only when the prefix contains no remaining geography; a
            # later alternative must stay bound to its original restriction.
            prefix = _without_policy(original[: contrast.start()])
            if not has_geographic_context(prefix):
                yield original[: contrast.start()]
                yield original[contrast.end() :]
                continue
        yield original


@dataclass(frozen=True)
class Scope:
    kinds: tuple[str, ...]
    end: int
    complete: bool

    def allows_israel(self, office: bool, central: bool) -> bool:
        return any(
            kind == "israel" or (kind == "noncentral" and not (office and central))
            for kind in self.kinds
        )

    def excludes_israel(self, office: bool, central: bool) -> bool:
        return (
            self.complete
            and bool(self.kinds)
            and all(
                kind == "foreign" or (kind == "noncentral" and office and central)
                for kind in self.kinds
            )
        )


def _scope(text: str, start: int) -> Scope:
    """Read adjacent places and their alternatives, never every place in a sentence."""
    prefix = re.match(
        r"\s*[-–—:(,]*\s*(?:(?:in|from|within|across)\s+)?(?:the\s+)?",
        text[start:],
        re.I,
    )
    pos = start + prefix.end()
    if not match_geographic_place(text, pos) and text[pos : pos + 1] in {"ב", "מ", "ל"}:
        pos += 1
    kinds: list[str] = []
    comma_qualifier = False
    conjunctive = False
    while match := match_geographic_place(text, pos):
        kind, end = match
        # 'Haifa, Israel' names one noncentral workplace, not an alternative
        # Israeli workplace. Disjunctive lists retain every offered option.
        if not (comma_qualifier and kinds[-1:] == ["noncentral"] and kind == "israel"):
            kinds.append(kind)
        separator = re.match(
            r"\s*(?:\(\s*(?:including|incl\.?|such as|e\.g\.)\s+|"
            r",\s*(?:(?:and|or|או)\s+)?|/\s*|\b(?:and|or|including|או)\s+|ו(?=[א-ת]))(?:the\s+)?",
            text[end:],
            re.I,
        )
        if not separator:
            # A prefix of a noun phrase is not a complete place ('דרום אמריקה').
            complete = bool(
                re.match(
                    r"\s*(?:$|[.()]|only\b|בלבד(?!\w)|[- ]based\b|office\b|hubs?\b|opportunity\b|"
                    r"(?:[-–—]\s*)?remote\b|full[ -]time\b|except\b|excluding\b|are eligible\b|may apply\b|"
                    r"(?:\d+|one|two|three|four|five|שלושה|ארבעה|חמישה)\s+(?:days?|ימים)\b)",
                    text[end:],
                    re.I,
                )
            )
            complete &= not (
                conjunctive
                and "foreign" in kinds
                and any(k in {"israel", "noncentral"} for k in kinds)
            )
            return Scope(tuple(kinds), end, complete)
        next_pos = end + separator.end()
        conjunctive |= separator.group().strip() == "ו"
        if not match_geographic_place(text, next_pos) and text[
            next_pos : next_pos + 1
        ] in {"ב", "מ", "ל"}:
            next_pos += 1
        if not match_geographic_place(text, next_pos):
            # An unknown alternative can include Israel. A conjunction introducing
            # a second obligation does not erase an explicit first obligation.
            uncertain_alternative = bool(
                re.search(r"\bor\b|/|או|ו", separator.group(), re.I)
            )
            if not re.match(
                r"(?:serving|supporting|with|without|excluding|except|"
                r"(?:and\s+)?(?:must|need|required|have|we|applicants|candidates)|"
                r"(?:\d+|one|two|three|four|five|שלושה|ארבעה|חמישה)\s+(?:days?|ימים))\b",
                text[next_pos:],
                re.I,
            ):
                uncertain_alternative = True
            return Scope(tuple(kinds), end, not uncertain_alternative)
        pos = next_pos
        comma_qualifier = separator.group().strip() == ","
    return Scope(tuple(kinds), pos, False)


def _closed_foreign_location(location: str) -> bool:
    """Every field alternative must resolve before any remote option can block."""
    for field in re.split(r"[;\n]", location):
        field = field.strip()
        remote = REMOTE.search(field)
        scope = _scope(field, 0)
        if remote and not scope.kinds:
            if field[: remote.start()].strip():
                return False
            scope = _scope(field, remote.end())
        tail = field[scope.end :]
        if remote and scope.end <= remote.start():
            tail = field[scope.end : remote.start()] + field[remote.end() :]
        if not scope.complete or not scope.kinds or tail.strip(" .)-–—"):
            return False
        if any(kind != "foreign" for kind in scope.kinds):
            return False
    return True


def _central_only(profile: Mapping[str, object]) -> bool:
    candidate = profile.get("candidate", {})
    candidate = candidate if isinstance(candidate, Mapping) else {}
    open_to = candidate.get("open_to", {})
    open_to = open_to if isinstance(open_to, Mapping) else {}
    geographies = profile.get(
        "candidate.open_to.geographies", open_to.get("geographies", [])
    )
    if not isinstance(geographies, list):
        return False
    if any(_normalized_location(g) in {"israel", "ישראל"} for g in geographies):
        return False
    location = profile.get("candidate.location", candidate.get("location", ""))
    return bool(CENTRAL.search(" ".join(map(str, geographies)) + " " + str(location)))


def _evidence(
    posting: Mapping[str, object], extraction: Mapping[str, object] | None
) -> tuple[str, list[str]]:
    location = str(posting.get("location") or "").strip()
    jd = str(posting.get("raw_jd") or posting.get("jd_text") or "").strip()
    quotes = [jd] if jd else []
    facts = extraction.get("facts", {}) if isinstance(extraction, Mapping) else {}
    if isinstance(facts, Mapping):
        for field in ("location", "remote"):
            fact = facts.get(field)
            quote = fact.get("evidence_quote") if isinstance(fact, Mapping) else None
            if isinstance(quote, str) and quote.strip() and (not jd or quote in jd):
                quotes.append(quote)
        if not location:
            fact = facts.get("location")
            if isinstance(fact, Mapping):
                value, quote = fact.get("value"), fact.get("evidence_quote")
                if (
                    isinstance(value, str)
                    and isinstance(quote, str)
                    and value in quote
                    and quote in quotes
                ):
                    location = value
    return location, quotes


def decide_location_eligibility(
    posting: Mapping[str, object],
    extraction: Mapping[str, object] | None,
    profile: Mapping[str, object],
) -> Eligibility:
    """Require permission AND no unresolved restriction; block only explicit evidence."""
    location, quotes = _evidence(posting, extraction)
    central = _central_only(profile)
    positive: list[str] = []
    unknown: list[str] = []
    blocked: list[str] = []
    israel_excluded: list[str] = []
    normalized_field = normalize_israeli_location(location)
    field_scope = _scope(normalized_field, 0)
    own_field = re.sub(r"\s+[-–—]\s+", ", ", OFFICE.sub(" ", normalized_field))
    own_field = re.sub(r"\boffice\b", " ", own_field, flags=re.I)
    own_field = re.sub(r"^(?:central|Midtown)\s+(Tel[ -]Aviv)\b", r"\1", own_field, flags=re.I)
    own_field = re.sub(r"\s+R&D\s+(?:center|location)\s*$", "", own_field, flags=re.I)
    own_scope = _scope(own_field, 0)
    own_israeli = bool(
        own_scope.complete
        and own_scope.kinds
        and set(own_scope.kinds) <= {"israel", "noncentral"}
        and not own_field[own_scope.end :].strip(" .()")
    )
    # An unfamiliar city with a closed Israeli country/district suffix can
    # resolve its own site description, while its commute scope stays unknown.
    own_city = ""
    if not own_israeli and "," in own_field:
        city, suffix = own_field.split(",", 1)
        country = _scope(suffix, 0)
        if (
            not _scope(city, 0).kinds
            and country.complete and country.kinds
            and set(country.kinds) <= {"israel", "noncentral"}
            and not suffix[country.end :].strip(" .()")
        ):
            own_israeli, own_city = True, city.strip()
            own_scope = country
    field_israeli = field_scope.complete and any(
        kind in {"israel", "noncentral"} for kind in field_scope.kinds
    )
    # Bare Remote supplies no conflicting country; explicit JD scopes still
    # resolve it. Missing, unparsed and contradictory fields stay unresolved.
    description_blocks_uncertain = field_israeli or not (
        (
            field_scope.complete
            and field_scope.kinds
            and "uncertain" not in field_scope.kinds
            and re.fullmatch(
                r"\s*(?:[- ]based)?[\s.)]*", normalized_field[field_scope.end :]
            )
        )
        or _closed_foreign_location(location)
        or re.fullmatch(r"\s*remote\s*", location, re.I)
    )
    office_required = (
        posting.get("work_mode") in {"on-site", "hybrid"}
        or posting.get("remote") is False
    )
    # A separate office-only JD can qualify a bare ATS location. Technical uses
    # of 'hybrid' and negated office wording cannot supply that requirement.
    for quote in quotes:
        if re.fullmatch(
            r"\s*(?:full[ -]time,?\s*)?(?:on[ -]?site|office[ -]based|hybrid)(?:\s+\d+\s+days)?[. ]*",
            quote,
            re.I,
        ):
            office_required = True
    for source, is_location in [
        (location, True),
        *((quote, False) for quote in quotes),
    ]:
        for original in _clauses(source):
            clause = original.replace("**", "").strip()
            if not clause:
                continue
            excerpt = original.strip()[:1000]
            own_workplace_unresolved = False
            if is_location:
                clause = normalize_israeli_location(clause)
                if own_city:
                    clause = OFFICE.sub(" ", clause)
            else:
                clause = _without_policy(clause)
                if own_israeli:
                    before_own_terms = clause
                    clause = _own_workplace_terms(
                        clause,
                        attendance=bool(own_city) or not (central and "noncentral" in own_scope.kinds),
                        own_location=own_field,
                    )
                    if clause is None:
                        own_workplace_unresolved = True
                        clause = before_own_terms
                    if (
                        clause != before_own_terms and not own_city
                        and not (central and "noncentral" in own_scope.kinds)
                    ):
                        positive.append(location)
            covered: list[tuple[int, int]] = []
            unrelated = bool(OTHER_ROLES.search(clause))

            def cover(start: int, end: int) -> None:
                covered.append((start, end))

            def scope_rule(
                start: int,
                scope: Scope,
                *,
                office: bool = False,
                mandatory: bool = False,
                remote_permission: bool = False,
            ) -> None:
                suffix = re.match(
                    r"\s*\)?\s*(?:[- ]based candidates\s+)?(?:only\b|בלבד)",
                    clause[scope.end :],
                    re.I,
                )
                end = scope.end + suffix.end() if suffix else scope.end
                cover(start, end)
                ambiguous = bool(
                    re.search(
                        r"\b(?:unless|if|provided|subject to|preferred|considered|optional|alternatively)\b",
                        clause,
                        re.I,
                    )
                )
                # A contrast introducing a requirement is not an exception.
                # A later contrast can offer another place/arrangement.
                ambiguous |= bool(re.search(r"\bbut\b", clause[scope.end :], re.I))
                ambiguous |= bool(
                    re.search(r"\b(?:office|hubs?)\s+or\b", clause[scope.end :], re.I)
                )
                if (
                    office
                    and "foreign" in scope.kinds
                    and any(k in {"israel", "noncentral"} for k in scope.kinds)
                ):
                    ambiguous |= not bool(
                        re.search(r"\bor\b|/", clause[start : scope.end], re.I)
                    )
                if ambiguous:
                    unknown.append(excerpt)
                elif scope.complete and (
                    scope.allows_israel(office, central)
                    or (remote_permission and "worldwide" in scope.kinds)
                ):
                    positive.append(excerpt)
                elif (mandatory or suffix) and scope.excludes_israel(office, central):
                    commute_block = (
                        office and central and set(scope.kinds) == {"noncentral"}
                    )
                    if (
                        not is_location
                        and description_blocks_uncertain
                        and not commute_block
                    ):
                        unknown.append(excerpt)
                    else:
                        blocked.append(excerpt)
                else:
                    unknown.append(excerpt)

            for negation in NEGATION.finditer(clause):
                scope = _scope(clause, negation.end())
                cover(negation.start(), scope.end)

            def is_covered(start: int, end: int | None = None) -> bool:
                end = start + 1 if end is None else end
                return any(left <= start and end <= right for left, right in covered)

            for technical in re.finditer(r"\bdata residency\b", clause, re.I):
                cover(technical.start(), technical.end())

            # All arrangement choices on this labeled line share one country.
            modes = re.match(r"Location\s*:\s*", clause, re.I)
            if modes and not unrelated:
                scope = _scope(clause, modes.end())
                if re.fullmatch(
                    r"\s*\(Onsite\s*/\s*Hybrid\s*/\s*Remote\s*[-–—]\s*"
                    r"Based on Client Requirement\)\s*[.]?",
                    clause[scope.end :],
                    re.I,
                ):
                    scope_rule(0, scope, mandatory=True, remote_permission=True)
                    cover(0, len(clause))

            for exclusion in EXCLUSION.finditer(clause):
                if is_covered(exclusion.start()):
                    continue
                scope = _scope(clause, exclusion.end())
                if not scope.kinds and not has_geographic_context(clause):
                    continue
                cover(exclusion.start(), scope.end)
                role_exclusion = bool(
                    REMOTE.search(clause)
                    or re.search(
                        r"\b(?:applicants|candidates|not open|not available)\b",
                        clause,
                        re.I,
                    )
                    or exclusion.group().lower().startswith("excluded countries")
                )
                if (
                    scope.complete
                    and re.match(
                        r"\s*(?:$|[.,;]|\b(?:and|or)\b)", clause[scope.end :], re.I
                    )
                    and any(kind in {"israel", "noncentral"} for kind in scope.kinds)
                    and role_exclusion
                ):
                    israel_excluded.append(excerpt)
                elif any(kind in {"israel", "noncentral"} for kind in scope.kinds):
                    unknown.append(excerpt)
                elif (
                    not scope.complete or not scope.kinds or "uncertain" in scope.kinds
                ):
                    unknown.append(excerpt)
            if ISRAEL_EXCLUDED.search(clause):
                israel_excluded.append(excerpt)

            for requirement in RESIDENCE.finditer(clause):
                if is_covered(requirement.start()):
                    continue
                scope = _scope(clause, requirement.end())
                if re.search(
                    r"\b(?:organization|company|clients?|customers?|headquarters)\b",
                    clause[: requirement.start()],
                    re.I,
                ):
                    cover(requirement.start(), scope.end)
                    unknown.append(excerpt)
                    continue
                mandatory = bool(
                    re.search(
                        r"must|need to|required to|only|חובה|נדרש|תושבי",
                        requirement.group(),
                        re.I,
                    )
                )
                scope_rule(requirement.start(), scope, mandatory=mandatory)

            for attendance in (
                *ATTENDANCE.finditer(clause),
                *REQUIRED_OFFICE.finditer(clause),
            ):
                if is_covered(attendance.start()):
                    continue
                scope = _scope(clause, attendance.end())
                office_end = re.match(r"\s+office\b", clause[scope.end :], re.I)
                if (
                    unrelated
                    or re.search(
                        r"\b(?:clients?|customers?)\b",
                        clause[: attendance.start()],
                        re.I,
                    )
                    or not office_end
                    or re.search(
                        r"\b(?:no need|not (?:require|required|requires|mandatory|necessary)|optional|may|can)\b",
                        clause[: attendance.end()],
                        re.I,
                    )
                ):
                    unknown.append(excerpt)
                else:
                    scope_rule(attendance.start(), scope, office=True, mandatory=True)
                    cover(attendance.start(), scope.end + office_end.end())

            # Unsupported attendance grammar must never let an Israel positive
            # bypass an office requirement (including an unknown office city).
            if (
                re.search(r"\boffice\b", clause, re.I)
                and re.search(
                    r"\b(?:days?|attendance|attend|requires?|required|must)\b",
                    clause,
                    re.I,
                )
                and not any(
                    is_covered(m.start())
                    for m in re.finditer(r"\boffice\b", clause, re.I)
                )
            ):
                unknown.append(excerpt)

            for office in OFFICE.finditer(clause):
                if is_covered(office.start()):
                    continue
                before, after = clause[: office.start()], clause[office.end() :]
                role_office = bool(
                    is_location
                    or not before.strip(" ,:-–—")
                    or re.search(
                        r"\b(?:role|position|job|work|working|schedule|arrangement)\b|המשרה",
                        before,
                        re.I,
                    )
                    or re.match(
                        r"\s+(?:role|position|work|schedule|arrangement)\b", after, re.I
                    )
                    or re.fullmatch(
                        r"\s*(?:full[ -]time[ ,:]*|this is a\s*)", before, re.I
                    )
                )
                if (
                    unrelated
                    or re.search(r"\b(?:clients?|customers?)\b", before, re.I)
                    or not role_office
                ):
                    unknown.append(excerpt)
                    continue
                lead = re.match(
                    r"\s*(?:(?:role|position|work|schedule|arrangement)\s*)?(?:(?:in|at)\s+|ב)?",
                    clause[office.end() :],
                    re.I,
                )
                scope = _scope(clause, office.end() + lead.end())
                if scope.kinds:
                    scope_rule(office.start(), scope, office=True, mandatory=True)
                elif is_location or re.fullmatch(
                    r"\s*(?:\d+\s+days)?[. ]*", clause[office.end() :]
                ):
                    loc_scope = _scope(normalize_israeli_location(location), 0)
                    if loc_scope.kinds:
                        scope_rule(
                            office.start(),
                            Scope(loc_scope.kinds, office.end(), loc_scope.complete),
                            office=True,
                            mandatory=True,
                        )
                    else:
                        unknown.append(excerpt)
                else:
                    unknown.append(excerpt)

            for remote in REMOTE.finditer(clause):
                if is_covered(remote.start()):
                    continue
                lead = re.match(
                    r"\s*(?:(?:opportunity|work|role|position)\s*)?",
                    clause[remote.end() :],
                    re.I,
                )
                scope = _scope(clause, remote.end() + lead.end())
                prefix_scope = _scope(clause, 0)
                if (
                    not scope.kinds
                    and prefix_scope.end <= remote.start()
                    and not clause[prefix_scope.end : remote.start()].strip(" -")
                ):
                    scope = Scope(
                        prefix_scope.kinds, remote.end(), prefix_scope.complete
                    )
                if not scope.kinds:
                    if re.match(
                        r"\s*(?:(?:opportunity|work|role|position)\s+)?(?:in|from|within)\b",
                        clause[remote.end() :],
                        re.I,
                    ):
                        unknown.append(excerpt)
                    # Worldwide remote is also a conventional explicit permission.
                    prefix_scope = _scope(clause, 0)
                    if (
                        prefix_scope.kinds == ("worldwide",)
                        and prefix_scope.end <= remote.start()
                    ):
                        positive.append(excerpt)
                    continue
                only = bool(
                    re.match(
                        r"\s*\)?\s*(?:[- ]based candidates\s+)?only\b",
                        clause[scope.end :],
                        re.I,
                    )
                )
                # Closed annotations and bounded current-role remote work scopes
                # do not need a redundant 'only'. Prose/customer geography does.
                tail = clause[scope.end :]
                annotation = bool(
                    re.fullmatch(r"[\s.)]*", tail)
                    and (
                        re.fullmatch(
                            r"\s*(?:Location\s*:\s*)?", clause[: remote.start()], re.I
                        )
                        or (
                            is_location
                            and prefix_scope.kinds
                            and prefix_scope.end <= remote.start()
                        )
                        or clause[remote.start() - 1 : remote.start()] == "("
                    )
                )
                bounded = bool(
                    re.match(
                        r"\s*(?:opportunity\s+)?within\s+", clause[remote.end() :], re.I
                    )
                )
                # The role base and the remote opportunity corroborate each other.
                role_base = bool(
                    re.match(r"\s+opportunity\b", tail, re.I)
                    and re.search(
                        r"\b(?:engineer|developer|role|position)\b.*\bbased in\b",
                        source,
                        re.I,
                    )
                )
                alternatives = re.search(
                    r"from one of our\s+", clause[: remote.start()], re.I
                )
                enumerated = False
                if alternatives:
                    hubs = _scope(clause, alternatives.end())
                    enumerated = bool(
                        re.fullmatch(
                            r"\s+hubs\s+or\s+", clause[hubs.end : remote.start()], re.I
                        )
                    )
                    if enumerated:
                        scope = Scope(
                            hubs.kinds + scope.kinds,
                            scope.end,
                            hubs.complete and scope.complete,
                        )
                # Preserve unparsed alternatives and conditional country approval.
                closed = annotation or bounded or role_base or enumerated
                if closed and re.search(r"\bor\b|/", tail, re.I):
                    scope = Scope(scope.kinds, scope.end, False)
                if (
                    is_location
                    and closed
                    and not _closed_foreign_location(source)
                    and not scope.allows_israel(False, central)
                    and "worldwide" not in scope.kinds
                ):
                    # An Israeli or unparsed field alternative can allow Israel.
                    closed = False
                    unknown.append(excerpt)
                scope_rule(
                    remote.start(),
                    scope,
                    mandatory=only or (closed and not unrelated),
                    remote_permission=True,
                )

            if REMOTE.search(location + " " + clause):
                for permission in PERMISSION.finditer(clause):
                    if not is_covered(permission.start()):
                        scope_rule(permission.start(), _scope(clause, permission.end()))

            # A closed 'X only' scope needs no residency verb. This handles
            # unfamiliar countries from the shared ISO vocabulary as well.
            for only in re.finditer(r"\bonly\b|בלבד", clause, re.I):
                if is_covered(only.start()):
                    continue
                scope = _scope(clause, 0)
                if scope.kinds and not clause[scope.end : only.start()].strip(" .-()"):
                    scope_rule(
                        0,
                        Scope(scope.kinds, only.end(), scope.complete),
                        mandatory=True,
                    )

            if is_location:
                scope = _scope(clause, 0)
                if (
                    scope.complete
                    and scope.kinds
                    and not clause[scope.end :].strip(" .)")
                ):
                    if "foreign" in scope.kinds and any(
                        k in {"israel", "noncentral"} for k in scope.kinds
                    ):
                        unknown.append(excerpt)
                    elif scope.allows_israel(office_required, central) and not (
                        central and "noncentral" in scope.kinds
                    ):
                        positive.append(excerpt)
                    elif office_required and scope.excludes_israel(True, central):
                        blocked.append(excerpt)

            # Frames supply their own context. The slot vocabulary is unbounded;
            # a known substring or a positive ATS location cannot resolve it.
            for frame in LOCATION_FRAME.finditer(clause):
                if not is_covered(frame.start(), frame.end()):
                    if _is_israeli_slot(frame["slot"]):
                        cover(frame.start(), frame.end())
                    else:
                        unknown.append(excerpt)
            for pattern in APPLICANT_FRAMES:
                for frame in pattern.finditer(clause):
                    if not is_covered(frame.start(), frame.end()):
                        # A language skill cannot erase another nationality or place.
                        slot, language_spans = LANGUAGE_SKILL.subn(" ", frame["slot"])
                        if language_spans:
                            slot = re.sub(r"\b(?:with|and)\b", " ", slot, flags=re.I)
                        slot = slot.strip()
                        if re.search(r"\bcitizens?\b|אזרח", frame.group(), re.I):
                            unknown.append(excerpt)
                        elif not slot or _is_israeli_slot(slot):
                            cover(frame.start(), frame.end())
                        elif not re.fullmatch(
                            r"(?:hire\s+)?the best", frame["slot"], re.I
                        ):
                            unknown.append(excerpt)
            if _qualified_credential(clause):
                unknown.append(excerpt)

            # An independently parsed, complete explicit geographic rule can
            # resolve itself. Otherwise a failed own-workplace consumption vetoes
            # eligibility even if its leftover words have no restriction keyword.
            if own_workplace_unresolved and not is_covered(0, len(clause.rstrip(" ."))):
                unknown.append(excerpt)

            for restriction in RESTRICTION.finditer(clause):
                if not is_covered(restriction.start()):
                    if has_geographic_context(clause):
                        unknown.append(excerpt)
        if is_location and unknown:
            description_blocks_uncertain = True
    if israel_excluded:
        blocked = israel_excluded
    if blocked:
        return {
            "eligibility": "blocked",
            "eligibility_reason": f'explicit location restriction: "{blocked[0]}"',
        }
    if unknown:
        return {
            "eligibility": "unknown",
            "eligibility_reason": f'unresolved location restriction: "{unknown[0]}"',
        }
    if positive:
        return {
            "eligibility": "eligible",
            "eligibility_reason": f'allowed location: "{positive[0]}"',
        }
    return {
        "eligibility": "unknown",
        "eligibility_reason": f'Israel/remote-from-Israel scope is unconfirmed: "{location or (quotes[0][:1000] if quotes else "no location evidence")}"',
    }
