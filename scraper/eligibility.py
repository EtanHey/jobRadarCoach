"""Precision-first local eligibility: unreadable restrictions veto every pass."""

from collections.abc import Mapping
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


CLAUSES = re.compile(r"[;\n]|(?<!\bu\.s)(?<!\bu\.s\.a)(?<!\be\.g)(?<=[a-z])\.\s+", re.I)
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
    r"\b(?:except|excluding|not open to|not available (?:in|from))\s+"
    r"(?:(?:applicants|candidates)\s+(?:from|in)\s+)?",
    re.I,
)
ISRAEL_EXCLUDED = re.compile(
    r"\bisrael\s+(?:is\s+)?(?:excluded|not (?:allowed|eligible))\b",
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
    r"\b(?:must|should|need to|required|requires?|only|based in|reside|residents?|located in|live in|"
    r"relocate|residence|residency|not (?:open|accepting|available|eligible)|except|excluding|eligible to work|citizens?(?:hip)?|"
    r"work authorization|time[ -]?zone|attendance|attend)\b|"
    r"\bdays?\s*(?:/\s*week|(?:each|per|a)\s+week)\b|"
    r"(?<!\w)(?:חובה|נדרש(?:ת|ים|ות)?|להתגורר|לגור|מגורים|תושבי\w*|רק|בלבד|למעט|פרט ל|לא)(?!\w)",
    re.I,
)
NEGATION = re.compile(
    r"\b(?:no need to|not (?:required|necessary) to)\s+(?:reside|live|be based|relocate)\s+(?:in|to)\s+|"
    r"\bnot\s+(?:remote|on[ -]?site|office[ -]based|hybrid)\b",
    re.I,
)
NON_LOCATION_POLICY = re.compile(
    r"\b(?:accommodations?|equal (?:employment )?opportunit\w*|"
    r"without regard to|regardless of|protected (?:personal )?characteristics|"
    r"privacy (?:act|policy)|GDPR|salary range|annual (?:base )?salary|"
    r"benefits (?:program|in this paragraph)|(?:office|on[ -]?site) perks|"
    r"on[ -]?site (?:courses|wellness|caf[ée])|dual citizens|"
    r"recruiters (?:correspond|only contact)|legitimate communication|"
    r"employment decisions|notify all applicants of their rights)\b",
    re.I,
)


def _non_location_policy(clause: str) -> bool:
    # A policy paragraph can also contain a real role requirement. Never erase
    # that requirement merely because accommodations or benefits are mentioned.
    return bool(NON_LOCATION_POLICY.search(clause)) and not (
        RESIDENCE.search(clause)
        or ATTENDANCE.search(clause)
        or REQUIRED_OFFICE.search(clause)
        or ISRAEL_EXCLUDED.search(clause)
        or any(
            _scope(clause, exclusion.end()).kinds or REMOTE.search(clause)
            for exclusion in EXCLUSION.finditer(clause)
        )
        or (
            re.search(
                r"(?<!\w)(?:חובה|נדרש(?:ת|ים|ות)?|מגורים|תושבי\w*|רק)(?!\w)", clause
            )
            and has_geographic_context(clause)
        )
        or any(
            has_geographic_context(clause[requirement.end() :])
            for requirement in re.finditer(
                r"\b(?:must|required|need to)\b", clause, re.I
            )
        )
        or (
            OFFICE.search(clause)
            and not re.search(r"\b(?:perks|courses|wellness|caf[ée])\b", clause, re.I)
        )
        or re.search(
            r"\b(?:must|required|requires?|only|need to)\b.*"
            r"\b(?:remote|reside|relocate|office|citizens?(?:hip)?|work authorization|time[ -]?zone)\b",
            clause,
            re.I,
        )
        or re.search(
            r"\b(?:citizens?(?:hip)?|work authorization|passport)\b.{0,40}"
            r"\b(?:required|only|mandatory)\b",
            clause,
            re.I,
        )
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
        r"\s*[-–—:(,]*\s*(?:(?:in|from|within|across)\s+)?(?:the\s+)?",
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
            if not (scope.kinds == ("uncertain",) and re.search(r"\bEMEA\b", field)):
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
            if is_location:
                clause = normalize_israeli_location(clause)
            elif _non_location_policy(clause):
                continue
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
                    blocked.append(excerpt)
                else:
                    unknown.append(excerpt)

            for negation in NEGATION.finditer(clause):
                scope = _scope(clause, negation.end())
                cover(negation.start(), scope.end)

            def is_covered(start: int) -> bool:
                return any(left <= start < right for left, right in covered)

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
                    annotation
                    and is_location
                    and re.search(r"\bEMEA\b", clause)
                    and scope.kinds == ("uncertain",)
                ):
                    scope = Scope(("foreign",), scope.end, scope.complete)
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

            for restriction in RESTRICTION.finditer(clause):
                if not is_covered(restriction.start()):
                    if has_geographic_context(clause):
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
