"""Precision-first local eligibility: unreadable restrictions veto every pass."""

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
import re
from typing import Literal, TypedDict

from scraper.geography import (
    COUNTRY_IDENTIFIERS,
    ISRAELI_CITY_NAMES,
    ISRAELI_PLACE_EQUIVALENTS,
    _normalized_location,
    has_geographic_context,
    match_description_place,
    match_geographic_place,
    normalize_israeli_location,
)


class Eligibility(TypedDict):
    eligibility: Literal["eligible", "blocked", "unknown"]
    eligibility_reason: str


CLAUSES = re.compile(
    r"[;\n]|(?<!\bu\.s)(?<!\bu\.s\.a)(?<!\be\.g)(?<!\bincl)"
    r"(?<!\bst)(?<!\brd)(?<!\bave)(?<!\bblvd)(?<=[a-z)א-ת])\.(?:\s+|(?=This\b))", re.I
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
    r"\b(?:passports?|work permits?|work authori[sz]ation|legal right to work|visas?|citizenship)\b|"
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
    r"(?:working\s+)?(?:in[ -]|from\s+|at\s+)(?:(?:our|the)\s+)?office\b|"
    r"\b(?:work|working|come|attend|visit)\s+(?:(?:in|at|from|to)\s+)?(?:our|the)\s+office\b",
    re.I,
)

WORKPLACE_NOUN = r"(?:offices?|workspace|hub|site|campus|HQ|headquarters|branch|location|studio|lab)"
# A slot is bounded by phrase grammar, not a gazetteer or capitalization.
WORKPLACE_WORD = (
    rf"(?!(?:{WORKPLACE_NOUN}|our|the|an?|and|or|with|from|in|at|near|to|of|"
    r"is|are|will|work|working|come|twice|once|days?|per|week|between|for)\b)[\w'-]+"
)
WORKPLACE_FRAMES = tuple(re.compile(pattern, re.I) for pattern in (
    rf"\b(?:our|the|an?)\s+(?P<slot>(?:{WORKPLACE_WORD}\s+)*){WORKPLACE_NOUN}\b",
    rf"\b{WORKPLACE_NOUN}\s+"
    r"(?:(?:(?:\d+|one|two|three|four|five)\s+)?days?\s+(?:per|a|each)\s+week\s+)?"
    rf"(?:in|at|near)\s+(?P<slot>{WORKPLACE_WORD}(?:\s+{WORKPLACE_WORD})*)",
    r"(?<!\w)[בהלמ]*משרד(?:י|ים)?\s+(?:(?:שלנו|החברה)\s+)?"
    r"ב(?P<slot>[א-ת'-]+(?:\s+(?!(?:עם|שלנו|של|שלושה|ימים|בשבוע)(?!\w))[א-ת'-]+)*)",
))

ADDRESS_PROXIMITY = (
    r"close to|near|next to|(?:within )?walking distance (?:of|from)|"
    r"just a short walk from"
)
# These local landmarks have an explicit city identity; arbitrary building or
# landmark names are not evidence that the address belongs to the posting city.
OWN_CITY_LANDMARKS = {
    "tel aviv": ("Sarona Market", "Neve Tzedek", "Azrieli"),
}


def _own_location_names(own_location: str) -> set[str]:
    own_location = normalize_israeli_location(own_location)
    places = {_normalized_location(own_location)}
    places.update(_normalized_location(part) for part in re.split(
        r"[,;()]|\s+and\s+", own_location, flags=re.I,
    ) if part.strip())
    for normalized in ISRAELI_CITY_NAMES:
        # A street address may precede a city in the structured location.
        if any(part.endswith(" " + normalized) for part in places):
            places.add(normalized)
    for canonical, aliases in ISRAELI_PLACE_EQUIVALENTS.items():
        if _normalized_location(canonical) in places:
            places.update(aliases)
    places.update({"israel", "israeli", "ישראל", "il"})
    return places


def _without_own_address(clause: str, own_location: str) -> str:
    """Consume bounded address details only beside an explicit own-city name."""
    clause = normalize_israeli_location(clause)
    cities = _own_location_names(own_location) & ISRAELI_CITY_NAMES
    city = "|".join(r"[\W_]+".join(map(re.escape, name.split()))
                    for name in sorted(cities, key=len, reverse=True) if name)
    if not city or not re.search(rf"(?<!\w)(?:{city})(?!\w)", clause, re.I):
        return clause
    # A named address component cannot eat another workplace or obligation.
    word = (rf"(?!(?i:{WORKPLACE_NOUN}|must|requires?|required|only|and|or|in|at|from|"
            r"to|of|with|citizenship|reside|live|relocate)\b)[A-Zא-ת][\w׳'’-]*")
    name = rf"{word}(?:\s+{word}){{0,3}}"
    street = r"(?i:Street|St|Road|Rd|Avenue|Ave|Blvd|Boulevard)\b\.?"
    local_names = [re.escape(place) for own_city in cities
                   for place in OWN_CITY_LANDMARKS.get(own_city, ())]
    local_place = "|".join(local_names) or r"(?!)"
    street_phrase = rf"(?:{name}\s+{street}|(?:רחוב|רח[׳']|שדרות)\s+{name})"
    destination = rf"(?:{street_phrase}|(?i:{city}|{local_place})(?!\w))"
    transit = (r"(?i:(?:the\s+)?(?:light rail(?: and train station)?|(?:both\s+)?train stations?|"
               r"metro|bus (?:station|terminal)|(?:highway|road)\s+\d+)|"
               r"ה?(?:רכבת(?: קלה)?|תחנה))(?!\w)")
    # Do not consume just a safe prefix of an unresolved destination. Separate
    # obligations may follow, but remain intact for the restriction parser.
    end = (r"(?=$|[,;.!?)]|\s+(?:and\s+(?:must|requires?|required|only)\b|"
           r"וחובה(?!\w)))")
    patterns = (
        rf"\b\d+\s+{name}\s+{street}(?:\s+(?i:in)\s+)?",
        rf"{name}\s+{street}\s+\d+\b",
        rf"(?:רחוב|רח[׳']|שדרות)\s+{name}\s+\d+\b",
        rf"(?i:between)\s+{destination}\s+(?i:and)\s+{destination}{end}",
        rf"(?i:{ADDRESS_PROXIMITY})\s+(?:{transit}|{destination}){end}",
        rf"(?i:in the)\s+{name}\s+(?i:area of)\s+(?=(?i:{city})(?!\w))",
        rf"(?i:in|at)\s+(?i:the\s+)?(?i:{local_place})\s+(?i:building|towers?)\b{end}",
        r"(?i:in Midtown)\b",
    )

    def consume(match: re.Match[str]) -> str:
        detail = match.group()
        for token in re.finditer(r"\b\w", detail):
            place = match_geographic_place(detail, token.start())
            if place and _normalized_location(detail[token.start():place[1]]) not in cities:
                return detail
        return "in " if re.search(r"\barea of\s+$", detail, re.I) else " "

    # A named office followed by its numbered address and the same city has
    # one workplace slot. Keep unknown labels without that address evidence.
    branded_office = re.compile(
        rf"(?i:the)\s+(?P<brand>{name})\s+(?P<city>(?i:{city}))\s+"
        rf"(?i:office),\s*(?i:located (?:in|at))\s+"
        rf"(?P<address>{name}\s+{street}\s+\d+)\s+"
        rf"(?P<address_city>(?i:{city}))(?!\w)"
    )
    for office in tuple(branded_office.finditer(clause)):
        if _normalized_location(office['city']) != _normalized_location(office['address_city']):
            continue
        detail = office['brand'] + " " + office['address']
        if any(match_geographic_place(detail, token.start())
               for token in re.finditer(r"\b\w", detail)):
            continue
        clause = clause.replace(office.group(), f"the {office['city']} office")
    for pattern in patterns:
        clause = re.sub(pattern, consume, clause)
    return re.sub(rf"(?i:the heart of|central|north)\s+(?=(?i:{city})(?!\w))", "", clause)


def _unresolved_workplace_phrase(
    clause: str, own_location: str, company: str, *, positive_signal: bool = False,
) -> bool:
    clause = normalize_israeli_location(clause)
    places = _own_location_names(own_location) if own_location else set()
    company_name = _normalized_location(normalize_israeli_location(company)) if company else ""
    if positive_signal:
        clause = re.sub(
            rf"(\b{WORKPLACE_NOUN}\s+)(?:is\s+)?(?:(?:located|situated)\s+)?(?=in\b|at\b|near\b)",
            r"\1", clause, flags=re.I,
        )
    for frame in WORKPLACE_FRAMES:
        for phrase in frame.finditer(clause):
            slot = _normalized_location(normalize_israeli_location(phrase["slot"]))
            slot = re.sub(r"^(?:(?:new|lovely|local|own)\b\s*)+", "", slot)
            if slot and slot == company_name:
                return True
            before = clause[:phrase.start()].strip(" -*•:")
            # Exclude organizational footprints and technical noun compounds;
            # these describe the company/product rather than a workplace.
            if (re.fullmatch(rf"(?:we|our company|the company|{re.escape(company)})\s+(?:has|have)", before, re.I)
                    and re.match(r"offices\s+(?:in|at|near)\b", phrase.group(), re.I)):
                continue
            if (re.search(r"\b(?:is|are)\s*$", before, re.I)
                    and re.search(r"\blab$", phrase.group(), re.I)):
                continue
            if any(
                re.search(rf"\b{noun}$", phrase.group(), re.I)
                and re.match(rf"\s+{suffix}\b", clause[phrase.end():], re.I)
                for noun, suffix in (("site", "reliability"), ("workspace", "security"), ("office", "pets"))
            ):
                continue
            if (re.fullmatch(r"our\s+(?:careers|company)\s+site", phrase.group(), re.I)
                    and re.search(r"\b(?:web|frontend|seeking a job)\b", clause, re.I)):
                continue
            if (re.match(r"(?:which|where)\b", phrase["slot"], re.I)
                    or re.fullmatch(r"(?:other|all|some)\s+times?", phrase["slot"], re.I)):
                continue
            if slot and slot not in places:
                return True
    return False


# Work-model words may be title-cased without naming a different workplace.
OWN_WORK_MODEL = re.compile(
    r"(?<!\w)(?:hybrid|remote|on[ -]?site|in[ -]office|office[ -]based|office|"
    r"flexible|model|schedule|environment|policy|work|working|"
    r"(?:\d+|one|two|three|four|five)\s+days?|per\s+week|a\s+week|each\s+week|weekly|"
    r"from\s+home|WFH|option|role|position|job|location|full[ -]time|"
    r"joining|smart|move|choose|"
    r"a|an|the|and|or|with|in|at|from|our|we|is|"
    r"[והב]*(?:היברידי(?:ת)?|מרחוק|משרד|גמיש(?:ה)?|מודל|מתכונת|סביבת|סביבה|"
    r"מדיניות|עבודה|עובדים|שבועי(?:ת)?|אפשרות)|"
    r"(?:\d+|יום אחד|יומיים|שני|שלושה|שלוש|ארבעה|ארבע|חמישה|חמש)\s*(?:ימים)?|"
    r"בשבוע|מהבית|שלנו|אנחנו|עם|או|ו)(?!\w)",
    re.I,
)
OWN_SITE = re.compile(
    r"\b(?:(?:(?:our|the|this)\s+)?(?:company|office|site|role|position|job)\s+(?:is\s+)?)?"
    r"(?:based|located|situated)\s+(?:in|at)\s+|"
    r"(?<!\w)(?:החברה|המשרד|המשרה)\s+(?:ממוקמת|ממוקם|מבוססת)\s+ב",
    re.I,
)


# Outside scopes can be explicit without a residence or office verb.
OUTSIDE_SCOPE = re.compile(
    r"\b(?:DACH|LATAM|APAC|EMEA|abroad|overseas|foreign countries)\b|"
    r"(?<!\w)[בלמוהש]*חו[\"״']?ל(?!\w)", re.I,
)
FOREIGN_NATIONALITY = re.compile(
    r"\b(?:American|British|German|French|Canadian|Australian|European|Swiss|"
    r"Dutch|Polish|Spanish|Italian|Irish|Portuguese|Indian|Chinese|Japanese|"
    r"Russian|Ukrainian|Brazilian|Mexican|Swedish|Norwegian|Danish|Finnish|"
    r"Austrian|Belgian|Romanian|Czech|Greek|Turkish|Singaporean)\b|"
    r"(?<!\w)(?:אמריקאי|בריטי|גרמני|צרפתי|קנדי|אירופי|אוסטרלי|הודי|רוסי)"
    r"(?:ת|ם|ות)?(?!\w)", re.I,
)
# Country-derived adjectives supplement irregular demonyms above, including
# compound names such as South African, without accepting fictional labels.
COUNTRY_NATIONALITY = re.compile(
    r"\b(?:" + "|".join(re.escape(name) for name in sorted(COUNTRY_IDENTIFIERS)
                         if len(name) > 3 and name != "israel") + r")(?:n|an|ian)\b", re.I,
)
OUTSIDE_TIME_ZONE = re.compile(
    r"\b(?:[PECM][SD]T|[ECW]EST|[ECW]ET|GMT|UTC|JST|AEST|AEDT|NZST)\b|"
    r"\b(?:Pacific|Eastern|Central|Mountain)\s+(?:time|hours)\b|"
    r"\b(?:America|Europe|Asia|Australia|Pacific)/[\w/+-]+", re.I,
)

NAMED_PROXIMITY = re.compile(
    r"\b(?:close to|near|within (?:walking|commuting) distance (?:of|from)|"
    r"a short walk from)\s+(?:the\s+)?(?P<place>[A-Z][\w'-]*)"
)
NAMED_WORKPLACE = re.compile(
    r"(?i:\b(?:(?:hybrid|on[ -]?site|office[ -]?based)(?: work)?(?: model)?|"
    r"work|working|attendance|office presence)\s+(?:in|at|from)\s+)"
    r"(?P<place>[A-Z][\w'-]*(?:\s+[A-Z][\w'-]*)*)"
)
SCHEDULED_WORKPLACE = re.compile(
    r"\b(?:hybrid|on[ -]?site|office[ -]?based)"
    r"(?:\s+(?:work|office|environment|model|schedule|role|\d+|one|two|three|four|five|days?|per|week|must|be|&)|,)*"
    r"\s+(?:in|at|from)\s+(?P<place>[\w'-]+(?:\s+[\w'-]+)*)", re.I,
)


def _nonown_work_destination(slot: str, own_location: str) -> bool:
    slot = slot.strip(" .")
    # These are work arrangements and generic jurisdictions, not destinations.
    if re.match(r"(?:our|the)\s+office\b|(?:a\s+)?hybrid\b", slot, re.I):
        return False
    if re.fullmatch(
        r"(?:(?:an?|the)\s+)?(?:approved|supported)\s+(?:jurisdiction|country|time zone)|"
        r"(?:an?\s+)?(?:office|home|person)|anywhere|worldwide|באזור זמן מאושר|אזור זמן מאושר|"
        r"בני?ין (?:החדש|הישן) של החברה",
        slot, re.I,
    ):
        return False
    slot = OWN_WORK_MODEL.sub(" ", slot).strip()
    scope = _scope(slot, 0)
    if scope.kinds and re.match(r"\s+involves?\b", slot[scope.end:], re.I):
        slot = slot[:scope.end]
    return bool(slot) and _normalized_location(slot) not in _own_location_names(own_location)


def _without_workplace_context(clause: str) -> str:
    # Customer/team geography describes others, not the applicant's workplace.
    # Do not discard a continuation that introduces another obligation.
    context = re.search(
        r"[, ]+(?:(?:supporting|serving) (?:clients?|customers?)|"
        r"and work daily with teammates)\b", clause, re.I,
    )
    if context and not (
        CREDENTIAL.search(clause[context.start():])
        or NATIONALITY_CREDENTIAL.search(clause[context.start():])
        or re.search(
            r"\b(?:must|required|requires?|only|attendance|attend|visits?|"
            r"reside|live|relocat(?:e|ion)|except|excluding|not open|security clearance)\b|חובה|נדרש",
            clause[context.start():], re.I,
        )
    ):
        clause = clause[:context.start()]

    return clause


def _positive_nonown_signal(clause: str, own_location: str, company: str) -> bool:
    """Require positive place evidence, not unexplained restriction wording."""
    clause = _without_workplace_context(clause)
    clause = re.sub(r"נדרש לעבוד בבני?ין (?:החדש|הישן) של החברה", " ", clause)
    clause = re.sub(r"\b(?:Asia/Jerusalem|MS Office)\b", " ", clause, flags=re.I)
    # Only consume the geographic span of non-applicant context; an appended
    # restriction must remain visible to the same signal and scope parsers.
    context = re.compile(
        r"\boccasional business trips to\s+|"
        rf"\b(?:we|our company|the company|{re.escape(company) if company else '(?!)'})\s+"
        r"(?:has|have) offices in\s+|"
        r"\bour clients offer remote opportunities within\s+", re.I,
    )
    for phrase in reversed(list(context.finditer(clause))):
        scope = _scope(clause, phrase.end())
        if scope.kinds and scope.complete:
            clause = clause[:phrase.start()] + " " + clause[scope.end:]
    clause = re.sub(
        r"\b(?:[\w-]+\s*/\s*)?[\w-]+-based\s+(?:CDN|infrastructure|cloud)\s+experience\b",
        " ", clause, flags=re.I,
    )
    if OUTSIDE_SCOPE.search(clause) or OUTSIDE_TIME_ZONE.search(clause):
        return True
    # Recognized own addresses have already been removed. Any remaining
    # destination relation is a non-own slot, including names outside the table.
    address_clause = re.sub(r"\bbetween office and home-based work\b", " ", clause, flags=re.I)
    if (re.search(rf"\b(?:{ADDRESS_PROXIMITY}|between)\s+", address_clause, re.I)
            and re.search(rf"\b{WORKPLACE_NOUN}\b|\bhybrid\b", address_clause, re.I)):
        return True
    if re.search(
        r"\b(?:in|at)\s+(?:the\s+)?"
        r"(?!(?:our|your|their|a|an|world)\b)[\w'-]+(?:\s+[\w'-]+){0,3}\s+"
        r"(?:building|towers?)\b", clause, re.I,
    ):
        return True
    if (CREDENTIAL.search(clause) or NATIONALITY_CREDENTIAL.search(clause)
            or re.search(r"\b(?:citizens?|applicants?|candidates?|residents?)\b|אזרח|מועמד|תושב", clause, re.I)):
        if (FOREIGN_NATIONALITY.search(LANGUAGE_SKILL.sub(" ", clause))
                or COUNTRY_NATIONALITY.search(LANGUAGE_SKILL.sub(" ", clause))):
            return True
    workplace_clause = re.sub(
        r"\b(?:(?:Chief Architect|CTO) Office|Cath lab|production branch|"
        r"secure workspace|accessible location|(?:local engineering|innovation) hub|"
        r"(?:live|CMS-driven) site|lab or field reference data|location intelligence|"
        r"App Studio|MS Office|posting location)\b", " ", clause, flags=re.I,
    )
    workplace_clause = re.sub(r"\bdedicated\s+(?=office\b)", "", workplace_clause, flags=re.I)
    if _unresolved_workplace_phrase(workplace_clause, own_location, company, positive_signal=True):
        return True
    for destination in LOCATION_FRAME.finditer(clause):
        if re.search(r"\bwork\b|לעבוד", destination.group(), re.I):
            if _nonown_work_destination(destination['slot'], own_location):
                return True
    places = _own_location_names(own_location)
    annotation = re.fullmatch(
        r"(?i:(?:hybrid|on[ -]?site|office[ -]?based)(?: work)?(?: model)?\s*[-:]?\s+)"
        r"(?P<place>[A-Z][\w'-]*(?:\s+[A-Z][\w'-]*)*)[. ]*", clause,
    )
    for workplace in [*NAMED_WORKPLACE.finditer(clause), *SCHEDULED_WORKPLACE.finditer(clause),
                      *([annotation] if annotation else [])]:
        place = workplace['place']
        if re.search(r"\b(?:experience|expertise|proficiency)\b", clause[:workplace.start()], re.I):
            continue
        if re.match(r"\s+(?:environments?|architectures?|methodology)\b", clause[workplace.end():], re.I):
            continue
        if place.casefold() in {"excel", "java"}:
            continue
        if (_nonown_work_destination(place, own_location)
                and _normalized_location(place) != _normalized_location(company)):
            return True
    for proximity in NAMED_PROXIMITY.finditer(clause):
        if _normalized_location(proximity['place']) not in places:
            return True
    for word in re.finditer(r"\b\w", clause):
        start = word.start()
        starts = [start] + [start + n for n in range(1, 4)
                            if re.fullmatch(r"[בלמוהש]+", clause[start:start + n])]
        for pos in starts:
            place = match_description_place(clause, pos)
            annotation = re.fullmatch(
                r"\s*(?:Location\s*:\s*)?(?:hybrid|on[ -]?site|remote)(?: work(?:ing)?(?: model)?)?\s*[-(]?\s*",
                clause[:pos], re.I,
            )
            code_slot = re.match(
                r"[A-Za-z]{2,3}(?=(?:[ -]based)?\s+(?:applicants?|candidates?|"
                r"citizens?(?:hip)?|persons?|residents?|visa|passport)\b)", clause[pos:], re.I,
            )
            if not place and (annotation or code_slot):
                place = match_description_place(clause.upper(), pos)
            if not place or place[0] == "worldwide":
                continue
            name = _normalized_location(clause[pos:place[1]])
            if name in places:
                continue
            if name in {"in", "at", "to", "or", "and", "as", "be", "by", "it"} and not clause[pos:place[1]].isupper():
                continue
            if (place[0] == "israel" and not (places & ISRAELI_CITY_NAMES)
                    and places & {"israel", "central israel"}):
                continue
            # ISO codes overlap ordinary words and technical acronyms. Require
            # a place position for these; UK/EU remain conventional in prose.
            if (len(name) <= 3 and not re.search(r"[א-ת]", name)
                    and name not in {"uk", "eu", "usa", "nyc", "u s", "u s a"}):
                before, after = clause[:pos], clause[place[1]:]
                if name in {"ai", "ml", "sc", "it", "ci", "cd"} and not re.match(
                    r"(?:[ -]based)?\s+(?:applicants?|candidates?|citizens?|residents?|work permits?)\b", after, re.I,
                ):
                    continue
                if not (re.search(r"\b(?:in|from|within|to)\s+(?:the\s+)?$", before, re.I)
                        or re.match(r"(?:[ -]based)?\s+(?:applicants?|candidates?|"
                                    r"citizens?(?:hip)?|persons?|residents?|office|hubs?|work|passport|visa)\b", after, re.I)
                        or re.fullmatch(r"\s*(?:Location\s*:\s*)?(?:hybrid|on[ -]?site|remote)(?: work(?:ing)?(?: model)?)?\s*[-(]?\s*", before, re.I)):
                    continue
                if (name == "us" and not annotation and not clause[pos:place[1]].isupper()
                        and not re.match(r"(?:[ -]based)?\s+(?:applicants?|candidates?|persons?|citizens?(?:hip)?|visa|passport)\b", after, re.I)):
                    continue
            return True
    return False


def _own_workplace_terms(
    clause: str, *, attendance: bool, own_location: str, company: str = ""
) -> str | None:
    """Satisfy own-site prose unless it contains a residual place/restriction."""
    # ATS tracking tags are not workplace sentences or geographic codes.
    clause = re.sub(r"#(?:LI|IL)-[\w-]+", " ", clause, flags=re.I)
    authorization = OWN_COUNTRY_AUTHORIZATION.search(clause)
    site = OWN_SITE.search(clause)
    workplace = (
        OFFICE.search(clause) or OWN_ATTENDANCE.search(clause)
        or re.search(r"\bin[ -](?:(?:our|the|an?)\s+)?office\b|"
                     r"\boffice\s+(?:is\s+)?(?:(?:located|situated)\s+)?"
                     r"(?:in|at|near|close to|between)\b|"
                     r"\boffice\s+(?:\d+|one|two|three|four|five)\s+days?\b|"
                     r"נדרש לעבוד בבני?ין (?:החדש|הישן) של החברה", clause, re.I)
    )
    if not (workplace or authorization or site):
        return clause
    if workplace and not attendance:
        return clause
    clause = re.sub(r"\bbetween office and home-based work\b", " ", clause, flags=re.I)
    # Address cleanup accepts complete, recognized destinations only. Preserve
    # every leftover relation, including lowercase unknown names.
    if re.search(rf"\b(?:{ADDRESS_PROXIMITY}|between)\s+", clause, re.I):
        return None

    clause = _without_workplace_context(clause)

    # Role titles and company introductions before the site verb are not places.
    # Their geography still gets checked below; only capitalization is exempt.
    prefix = clause[:site.start()] if site and not workplace else ""
    if not re.search(r"\b(?:looking for|recruiting|hiring)\b", prefix, re.I):
        prefix = ""
    # Recognize pronouns before removing names: 'with Tel Aviv us' is not 'with us'.
    remainder = re.sub(r"\b(?:join|with|contact)\s+us\b", " ", clause, flags=re.I)
    remainder = re.sub(r"\b(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)(?:day|sday|nesday|rsday|urday)?\b", " ", remainder)
    remainder = re.sub(r"\b(?:at|in)\s+(?:other|all|some)\s+times?\b", " ", remainder, flags=re.I)
    remainder = OWN_COUNTRY_AUTHORIZATION.sub(" ", remainder)
    remainder = OWN_SITE.sub(" ", remainder)
    remainder = re.sub(r"\b(?:must|required to|requires?|need to)\s+(?:employees to )?"
                       r"(?:work\s+)?(?=\d+|one|two|three|four|five)", " ", remainder, flags=re.I)
    remainder = re.sub(r"נדרש לעבוד בבני?ין (?:החדש|הישן) של החברה", " ", remainder)
    remainder = normalize_israeli_location(remainder)
    places = _own_location_names(own_location)
    own_place_consumed = False
    for place in sorted(places, key=len, reverse=True):
        pattern = r"(?<!\w)(?:[במל])?" + r"[\W_]+".join(map(re.escape, place.split())) + r"(?!\w)"
        remainder, count = re.subn(pattern, " ", remainder, flags=re.I)
        own_place_consumed |= bool(count)
    if site and not own_place_consumed:
        return None
    if company:
        remainder = re.sub(r"(?<!\w)" + re.escape(company) + r"(?!\w)", " ", remainder, flags=re.I)

    # Inspect place positions before deleting prepositions/work-model words.
    # Unknown lowercase cities are still places in 'our warsaw office'.
    for phrase in re.finditer(
        r"\b(?:in|at|to|near|from)\s+(?:(?:our|the|an?|approved)\s+)*"
        r"(?P<noun>[\w'-]+)(?:\s+(?P<next>[\w'-]+))?", remainder, re.I,
    ):
        noun = phrase['noun'].casefold()
        following = (phrase['next'] or '').casefold()
        if (following in {"office", "offices", "site", "hub", "headquarters"}
                and noun not in {"office", "local", "own", "new"}):
            return None
        before = remainder[:phrase.start()]
        if re.search(r"\b(?:presence|visits?|attendance|office|site|work|working|hybrid)\s*$", before, re.I):
            if noun not in {"office", "offices", "home", "person", "more", "work", "working", "hybrid", "anywhere"}:
                return None
    if re.search(r"(?:משרד|נוכחות)\s+(?:שלנו\s+)?ב[א-ת]+|(?<!\w)וב[א-ת]+", remainder):
        return None
    remainder = OWN_WORK_MODEL.sub(" ", remainder)
    # A lone residual code in a work-model annotation is a place in any casing.
    bare = remainder.strip(" .,:;()-–—")
    code = match_geographic_place(bare.upper())
    if code and code[1] == len(bare):
        return None
    for word in re.finditer(r"\b\w", remainder):
        start = word.start()
        if match_geographic_place(remainder, start):
            return None
        for length in range(1, 4):
            if (re.fullmatch(r"[בלמוהש]+", remainder[start:start + length])
                    and match_geographic_place(remainder, start + length)):
                return None
    # Sentence-initial capitalization is grammatical, not a place signal.
    first = re.search(r"[A-Za-z]+", clause)
    for word in re.finditer(r"\b[A-Z][A-Za-z'-]*\b", remainder):
        if not ((first and word.group() == first.group()) or re.search(
            r"\b" + re.escape(word.group()) + r"\b", prefix,
        )):
            return None
    # Independent requirements must still reach the general restriction parser.
    if (CREDENTIAL.search(remainder) or NATIONALITY_CREDENTIAL.search(remainder)
            or re.search(r"security clearance|סיווג ביטחוני", remainder, re.I)
            or (RESTRICTION.search(remainder) and (
                has_geographic_context(remainder) or RESIDENCE.search(remainder)
                or LOCATION_FRAME.search(remainder) or EXCLUSION.search(clause)
                or ISRAEL_EXCLUDED.search(clause)
            ))):
        return None
    return " "


def _without_policy(text: str) -> str:
    text = EEO_LIST.sub(" ", text)
    text = TEAM_CITIZENS.sub(r"\1 ", text)
    text = re.sub(r"\b(?:this (?:role|position) )?does not offer visa sponsorship\b", " ", text, flags=re.I)
    text = re.sub(r"רישיון\s+\S+\s+לתוכנת\s+\S+", " ", text)
    text = re.sub(r"\bsparse hybrid models\b", " ", text, flags=re.I)
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
    normalized_field = _without_own_address(location, location)
    field_scope = _scope(normalized_field, 0)
    own_field = re.sub(r"\s+[-–—]\s+", ", ", OFFICE.sub(" ", normalized_field))
    own_field = re.sub(r"\boffice\b", " ", own_field, flags=re.I)
    own_field = REMOTE.sub(" ", own_field)
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
                clause = (
                    _without_own_address(clause, own_field) if own_israeli
                    else normalize_israeli_location(clause)
                )
                if own_city:
                    clause = OFFICE.sub(" ", clause)
            else:
                clause = _without_policy(clause)
                if own_israeli:
                    clause = _without_own_address(clause, own_field)
                # Inspect intact workplace slots before own-site cleanup can
                # erase company names, prepositions, or attendance wording.
                own_workplace_unresolved = _unresolved_workplace_phrase(
                    clause, own_field if own_israeli else "",
                    str(posting.get("company") or ""),
                )
                if own_israeli:
                    nonown_signal = _positive_nonown_signal(
                        clause, own_field, str(posting.get("company") or ""),
                    )
                    if (not nonown_signal and not own_city
                            and not (central and "noncentral" in own_scope.kinds)
                            and not any(
                                set(_scope(clause, exclusion.end()).kinds) & {"israel", "noncentral"}
                                for exclusion in EXCLUSION.finditer(clause)
                            )
                            and not ISRAEL_EXCLUDED.search(clause)
                            and not re.search(r"\bnot accepting\b", clause, re.I)):
                        positive.append(location)
                        continue
                    before_own_terms = clause
                    clause = _own_workplace_terms(
                        clause,
                        attendance=bool(own_city) or not (central and "noncentral" in own_scope.kinds),
                        own_location=own_field,
                        company=str(posting.get("company") or ""),
                    )
                    if clause is None or (nonown_signal and not clause.strip()):
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

            for attend in re.finditer(
                r"^\s*(?:[-*•]\s*)?(?:applicants?|candidates?) must attend (?:our|the)\s+", clause, re.I,
            ):
                scope = _scope(clause, attend.end())
                if scope.complete and re.fullmatch(
                    r"\s+office (?:\d+|one|two|three|four|five) days? per week[. ]*",
                    clause[scope.end:], re.I,
                ):
                    cover(attend.start(), len(clause))
                    if scope.excludes_israel(True, central):
                        blocked.append(excerpt)
                    elif scope.allows_israel(True, central):
                        positive.append(excerpt)

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
                based_remote = bool(
                    not is_location and prefix_scope.kinds
                    and re.fullmatch(r"-based\s+", clause[prefix_scope.end:remote.start()], re.I)
                    and re.fullmatch(r"\s+(?:role|position|job)[. ]*", clause[remote.end():], re.I)
                )
                if based_remote:
                    scope_rule(0, Scope(prefix_scope.kinds, len(clause), True),
                               mandatory=True, remote_permission=True)
                    continue
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
            # resolve itself. Otherwise a residual workplace place/restriction vetoes
            # eligibility even if its leftover words have no restriction keyword.
            if own_workplace_unresolved and not is_covered(0, len(clause.rstrip(" ."))):
                unknown.append(excerpt)

            for restriction in RESTRICTION.finditer(clause):
                if not is_covered(restriction.start()):
                    if has_geographic_context(clause):
                        unknown.append(excerpt)
            if not is_location and own_israeli and nonown_signal:
                # Only parsed spans can discharge evidence. A covered local
                # permission cannot erase a separate foreign destination.
                residual = list(clause)
                for left, right in covered:
                    residual[left:right] = " " * (right - left)
                if _positive_nonown_signal(
                    "".join(residual), own_field, str(posting.get("company") or ""),
                ):
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
