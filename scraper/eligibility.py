"""Precision-first local eligibility: unreadable restrictions veto every pass."""

from collections.abc import Mapping
from dataclasses import dataclass
import re
from typing import Literal, TypedDict

from scraper.geography import _normalized_location, match_geographic_place


class Eligibility(TypedDict):
    eligibility: Literal["eligible", "blocked", "unknown"]
    eligibility_reason: str


CLAUSES = re.compile(r"[;\n]|(?<!\bu\.s)(?<!\bu\.s\.a)(?<!\be\.g)(?<=[a-z])\.\s+", re.I)
CENTRAL = re.compile(
    r"\b(?:central|cent(?:er|re)(?: of (?:the country|israel))?|gush dan)\b|מרכז", re.I
)
OFFICE = re.compile(
    r"\b(?:on[ -]?site|office[ -]based|hybrid)(?!\s+(?:cloud|mobile|apps|infrastructure)\b)\b|"
    r"היברידי(?:ת)?|(?:עבודה|המשרה)\s+במשרד",
    re.I,
)
RESIDENCE = re.compile(
    r"\b(?:(?:must|should|need to|required to)\s+(?:already\s+)?(?:be\s+)?"
    r"(?:reside|live|based|located)\s+in|(?:must|need to|required to)\s+relocate\s+to|"
    r"only\s+(?:candidates|applicants)\s+(?:based|located)\s+in|"
    r"(?:be\s+)?based\s+in|residents?\s+of)\s+|"
    r"(?:חובה|נדרש)\s+(?:להתגורר|לגור)\s+ב|ל?תושבי\s+",
    re.I,
)
EXCLUSION = re.compile(
    r"\b(?:except|excluding|not open to|not available (?:in|from))\s+"
    r"(?:(?:applicants|candidates)\s+(?:from|in)\s+)?",
    re.I,
)
ISRAEL_EXCLUDED = re.compile(
    r"\bisrael\s+(?:is\s+)?(?:excluded|not (?:allowed|eligible))\b",
    re.I,
)
REMOTE = re.compile(r"\bremot(?:e|ely)\b|(?:עבודה\s+)?מרחוק", re.I)
PERMISSION = re.compile(
    r"\bopen to (?:candidates|applicants) (?:in|from)\s+|"
    r"ניתן לעבוד מכל מקום ב",
    re.I,
)
# A recognized rule must account for every restriction span. Unsupported grammar,
# unknown places, citizenship, work authorization and time zones remain unknown.
RESTRICTION = re.compile(
    r"\b(?:must|should|need to|required|only|based in|reside|residents?|located in|live in|"
    r"relocate|residence|residency|not (?:open|accepting|available|eligible)|except|excluding|eligible to work|citizens?(?:hip)?|"
    r"work authorization|time[ -]?zone)\b|"
    r"חובה|נדרש|להתגורר|לגור|מגורים|תושבי|רק|בלבד|למעט|פרט ל|לא\s",
    re.I,
)
NEGATION = re.compile(
    r"\b(?:no need to|not (?:required|necessary) to)\s+(?:reside|live|be based|relocate)\s+(?:in|to)\s+|"
    r"\bnot\s+(?:remote|on[ -]?site|office[ -]based|hybrid)\b",
    re.I,
)


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
        r"\s*[-–—:(]*\s*(?:(?:in|from|within|across)\s+)?(?:the\s+)?",
        text[start:],
        re.I,
    )
    pos = start + prefix.end()
    if not match_geographic_place(text, pos) and text[pos : pos + 1] in {"ב", "מ"}:
        pos += 1
    kinds: list[str] = []
    comma_qualifier = False
    while match := match_geographic_place(text, pos):
        kind, end = match
        # 'Haifa, Israel' names one noncentral workplace, not an alternative
        # Israeli workplace. Disjunctive lists retain every offered option.
        if not (comma_qualifier and kinds[-1:] == ["noncentral"] and kind == "israel"):
            kinds.append(kind)
        separator = re.match(
            r"\s*(?:,\s*(?:(?:and|or)\s+)?|/\s*|\b(?:and|or|including)\s+)(?:the\s+)?",
            text[end:],
            re.I,
        )
        if not separator:
            return Scope(tuple(kinds), end, True)
        next_pos = end + separator.end()
        if not match_geographic_place(text, next_pos):
            # An unknown alternative can include Israel. A conjunction introducing
            # a second obligation does not erase an explicit first obligation.
            uncertain_alternative = bool(
                re.search(r"\bor\b|/", separator.group(), re.I)
            )
            return Scope(tuple(kinds), end, not uncertain_alternative)
        pos = next_pos
        comma_qualifier = separator.group().strip() == ","
    return Scope(tuple(kinds), pos, False)


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
        for original in CLAUSES.split(source):
            clause = original.replace("**", "").strip()
            if not clause:
                continue
            excerpt = original.strip()[:1000]
            covered: list[tuple[int, int]] = []

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
                        r"\b(?:unless|if|provided|subject to|preferred|considered|optional|but|alternatively)\b",
                        clause,
                        re.I,
                    )
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
                    blocked.append(excerpt)
                else:
                    unknown.append(excerpt)

            for negation in NEGATION.finditer(clause):
                scope = _scope(clause, negation.end())
                cover(negation.start(), scope.end)

            def is_covered(start: int) -> bool:
                return any(left <= start < right for left, right in covered)

            for exclusion in EXCLUSION.finditer(clause):
                if is_covered(exclusion.start()):
                    continue
                scope = _scope(clause, exclusion.end())
                cover(exclusion.start(), scope.end)
                role_exclusion = bool(
                    REMOTE.search(clause)
                    or re.search(
                        r"\b(?:applicants|candidates|not open|not available)\b",
                        clause,
                        re.I,
                    )
                )
                if (
                    any(kind in {"israel", "noncentral"} for kind in scope.kinds)
                    and role_exclusion
                ):
                    blocked.append(excerpt)
                elif any(kind in {"israel", "noncentral"} for kind in scope.kinds):
                    unknown.append(excerpt)
                elif (
                    not scope.complete or not scope.kinds or "uncertain" in scope.kinds
                ):
                    unknown.append(excerpt)
            if ISRAEL_EXCLUDED.search(clause):
                blocked.append(excerpt)

            for requirement in RESIDENCE.finditer(clause):
                if is_covered(requirement.start()):
                    continue
                scope = _scope(clause, requirement.end())
                mandatory = bool(
                    re.search(
                        r"must|need to|required to|only|חובה|נדרש|תושבי",
                        requirement.group(),
                        re.I,
                    )
                )
                scope_rule(requirement.start(), scope, mandatory=mandatory)

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
                if not role_office:
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
                    loc_scope = _scope(location, 0)
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
                if not scope.kinds:
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
                scope_rule(
                    remote.start(), scope, mandatory=only, remote_permission=True
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

            for restriction in RESTRICTION.finditer(clause):
                if not is_covered(restriction.start()):
                    if restriction.group().casefold() in {
                        "must",
                        "required",
                        "should",
                        "only",
                        "need to",
                        "רק",
                    }:
                        has_places = any(
                            match_geographic_place(clause, word.start())
                            for word in re.finditer(r"\b\w", clause)
                        )
                        has_geo_words = re.search(
                            r"\b(?:in|from|within|remote|reside|residents?|live|located|based|citizens?|hours|work|candidates|applicants|time[ -]?zone)\b|מגורים|תושבי|להתגורר|לגור|מרחוק|בישראל",
                            clause,
                            re.I,
                        )
                        if not has_places and not has_geo_words:
                            continue
                    unknown.append(excerpt)
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
