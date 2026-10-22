"""Local post-score location eligibility; never changes professional fit advice."""

from collections.abc import Mapping
import re
from typing import Literal, TypedDict

from scraper.geography import (
    COUNTRY_CITY_ALIASES,
    COUNTRY_IDENTIFIERS,
    _city_matches_country,
    _normalized_location,
)


class Eligibility(TypedDict):
    eligibility: Literal["eligible", "blocked", "unknown"]
    eligibility_reason: str


US = r"(?:u\.?s\.?a?\.?|(?:continental\s+)?united states(?: of america)?)"
FOREIGN_COUNTRIES = "|".join(
    re.escape(country)
    for country in sorted(COUNTRY_IDENTIFIERS, key=len, reverse=True)
    if len(country) > 3 and "israel" not in country
)
FOREIGN_SCOPE = rf"(?:{US}|{FOREIGN_COUNTRIES}|eu|europe(?:an union)?|uk)"
FOREIGN_CITIES = "|".join(
    re.escape(city)
    for country, cities in COUNTRY_CITY_ALIASES.items()
    if country != "israel"
    for city in sorted(cities, key=len, reverse=True)
)
FOREIGN_PLACE = re.compile(rf"\b(?:{FOREIGN_SCOPE}|{FOREIGN_CITIES})\b", re.I)
CITY_RESIDENCY = re.compile(
    rf"\b(?:must|should|need to|required to)\s+(?:already\s+)?"
    rf"(?:reside in|live in|be based in|be located in|relocate to)\s+(?:the\s+)?(?:{FOREIGN_CITIES})\b",
    re.I,
)
ISRAEL_EXCLUSION = re.compile(
    r"\b(?:except|excluding|not available in|not available from)\s+israel\b|"
    r"\bisrael\s+(?:is\s+)?(?:excluded|not (?:allowed|eligible))\b", re.I,
)
HEBREW_US_ONLY = re.compile(r"(?:ל?תושבי)\s+(?:ארצות הברית|ארה[\"״]?ב)\s+בלבד")
ISRAEL_RESIDENCY = re.compile(
    r"\b(?:must|should|need to|required to)\s+(?:already\s+)?"
    r"(?:reside|live|be based|be located)\s+in\s+israel\b", re.I,
)
CLAUSES = re.compile(
    r"[;\n]|(?<!\bu\.s)(?<!\bu\.s\.a)(?<!\be\.g)(?<=[a-z])\.\s+", re.I
)
REMOTE_SCOPE = re.compile(
    rf"\bremot(?:e|ely)(?: opportunity| work| role| position)?\s*[-:(]?\s*"
    rf"(?:(?:from|within|in|across|based in)\s+)?(?:the\s+)?{FOREIGN_SCOPE}\b",
    re.I,
)
RESIDENCY = re.compile(
    rf"\b(?:must|should|need to|required to)\s+(?:already\s+)?(?:reside|live|be based|be located)\s+in\s+(?:the\s+)?{FOREIGN_SCOPE}\b|"
    rf"\b{FOREIGN_SCOPE}[ -]+based candidates only\b|\b(?:eu|europe|us|u\.s\.)[ -]+only\b|"
    r"\b(?:israel (?:is )?(?:excluded|not (?:allowed|eligible))|not available (?:in|from) israel)\b",
    re.I,
)
GLOBAL_REMOTE = re.compile(
    r"\bremote\s+\(?\s*(?:from |within |in |work )?(?:israel|worldwide|globally|anywhere in the world|all countries)\b|"
    r"\b(?:worldwide|global(?:ly)?) remote\b|\bwork (?:remotely )?from anywhere in the world\b",
    re.I,
)
ONSITE = re.compile(r"\b(?:on[ -]?site|office[ -]based|hybrid)\b", re.I)
ROLE_ONSITE = re.compile(
    r"(?:^|[;,:])\s*(?:full[ -]time[ ,:]+)?(?:on[ -]?site|office[ -]based|hybrid)\b|"
    r"\b(?:role|position|job|work|working|schedule|arrangement) (?:is |will be |requires |from )?(?:on[ -]?site|office[ -]based|hybrid)\b|"
    r"\b(?:on[ -]?site|hybrid) (?:role|position|work|schedule|arrangement|[0-9]+ days)\b",
    re.I,
)


def _requires_office(posting: Mapping[str, object], quotes: list[str]) -> bool:
    return bool(
        posting.get("work_mode") in {"on-site", "hybrid"}
        or posting.get("remote") is False
        or ONSITE.search(str(posting.get("location") or ""))
        or any(
            ROLE_ONSITE.search(clause.replace("**", ""))
            and not re.search(r"\bnot (?:on[ -]?site|office[ -]based|hybrid)\b", clause, re.I)
            for quote in quotes
            for clause in re.split(r"[;\n]", quote)
        )
    )


CENTRAL = re.compile(
    r"\b(?:central|cent(?:er|re)(?: of (?:the country|israel))?|gush dan)\b|מרכז", re.I
)
NONCENTRAL = re.compile(
    r"\b(?:sasa|galilee|haifa|jerusalem|be.?er sheva|yokneam|northern|southern)\b|חיפה|ירושלים|באר שבע|יקנעם",
    re.I,
)


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


def decide_location_eligibility(
    posting: Mapping[str, object],
    extraction: Mapping[str, object] | None,
    profile: Mapping[str, object],
) -> Eligibility:
    """Quote posting evidence; conflicting signals and absent scope stay unknown.

    A generic US listing is not a residency restriction. Remote must explicitly
    include Israel/worldwide. Citizenship and authorization are never a pass.
    """
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
    if not location and isinstance(facts, Mapping):
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
    # Evaluate scope within a sentence/line; benefits and customer geographies
    # elsewhere in the JD must not turn into residence/remote requirements.
    evidence = [location, *quotes]
    positive: list[str] = []
    negative: list[str] = []
    restrictions: list[str] = []
    normalized = _normalized_location(location)
    israel = bool(
        re.search(r"\b(?:israel|ישראל)\b", normalized)
    ) or _city_matches_country(location, "israel")
    foreign_location = bool(re.search(rf"\b{FOREIGN_SCOPE}\b", location, re.I))
    if israel and not foreign_location:
        if _central_only(profile) and NONCENTRAL.search(location):
            if _requires_office(posting, quotes):
                restrictions.append(location)
        else:
            positive.append(location)
    for quote in evidence:
        for original_clause in CLAUSES.split(quote):
            clause = original_clause.replace("**", "")
            if not clause.strip():
                continue
            excerpt = original_clause.strip()[:1000]
            if ISRAEL_EXCLUSION.search(clause) or HEBREW_US_ONLY.search(clause):
                restrictions.append(excerpt)
            if re.search(
                r"\b(?:not|no) (?:required|necessary) to (?:reside|live|be based|relocate)\b|"
                r"\bnot (?:remote|on[ -]?site|office[ -]based|hybrid)\b",
                clause,
                re.I,
            ):
                continue
            if CITY_RESIDENCY.search(clause):
                restrictions.append(excerpt)
            if ROLE_ONSITE.search(clause) and (
                FOREIGN_PLACE.search(clause)
                or (_central_only(profile) and NONCENTRAL.search(clause))
            ):
                restrictions.append(excerpt)
            includes_israel = bool(
                re.search(
                    r"\b(?:and|or|including) israel\b|\bisrael\s+(?:or|and)\b",
                    clause, re.I,
                )
            )
            inclusive_scope = bool(
                includes_israel
                and (REMOTE_SCOPE.search(clause) or RESIDENCY.search(clause))
            )
            if inclusive_scope:
                positive.append(original_clause.strip()[:1000])
            if (
                GLOBAL_REMOTE.search(clause)
                or ISRAEL_RESIDENCY.search(clause)
                or re.search(r"עבודה מרחוק מישראל\b", clause)
            ):
                positive.append(original_clause.strip()[:1000])
            if RESIDENCY.search(clause) or REMOTE_SCOPE.search(clause):
                # An explicitly inclusive scope wins within one clause, e.g.
                # "Remote in the US, Canada and Israel".
                if not re.search(r"\bisrael\b|\bworldwide\b", clause, re.I):
                    negative.append(original_clause.strip()[:1000])
                elif RESIDENCY.search(clause) and not inclusive_scope:
                    negative.append(original_clause.strip()[:1000])
            if (
                re.search(
                    r"\b(?:location\s*:?[ ]*|client location\s*:[ ]*)", clause, re.I
                )
                and not israel
            ):
                if foreign_location or re.search(r"\bnew york\b", clause, re.I):
                    negative.append(original_clause.strip()[:1000])
            if (
                "within the country of employment" in clause.casefold()
                and foreign_location
            ):
                negative.append(original_clause.strip()[:1000])
    onsite = _requires_office(posting, quotes)
    if onsite and FOREIGN_PLACE.search(location) and not israel:
        negative.append(location)
    if restrictions:
        return {
            "eligibility": "blocked",
            "eligibility_reason": f'location restriction: "{restrictions[0]}"',
        }
    if israel and foreign_location and not positive:
        return {
            "eligibility": "unknown",
            "eligibility_reason": f'conflicting location scope: "{location}"',
        }
    if positive and negative:
        return {
            "eligibility": "unknown",
            "eligibility_reason": f'conflicting location evidence: "{positive[0]}"; "{negative[0]}"',
        }
    if negative:
        return {
            "eligibility": "blocked",
            "eligibility_reason": f'location restriction: "{negative[0]}"',
        }
    if positive:
        return {
            "eligibility": "eligible",
            "eligibility_reason": f'allowed location: "{positive[0]}"',
        }
    return {
        "eligibility": "unknown",
        "eligibility_reason": f'Israel/remote-from-Israel scope is unconfirmed: "{location or jd[:1000] or "no location evidence"}"',
    }
