"""Deterministic, I/O-free normalization of raw posting facts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
import hashlib
import json
import re
from urllib.parse import urlsplit


NORMALIZER_VERSION = "3"
LINK_STATUSES = frozenset({"no_link", "available", "invalid_url"})

_ISRAEL = {
    "tel aviv": ("IL", "IL-TA", "Tel Aviv"), "tel aviv-yafo": ("IL", "IL-TA", "Tel Aviv"),
    "jerusalem": ("IL", "IL-JM", "Jerusalem"), "haifa": ("IL", "IL-HA", "Haifa"),
    "herzliya": ("IL", "IL-TA", "Herzliya"), "petah tikva": ("IL", "IL-TA", "Petah Tikva"),
    "ramat gan": ("IL", "IL-TA", "Ramat Gan"), "ra'anana": ("IL", "IL-TA", "Ra'anana"),
    "raanana": ("IL", "IL-TA", "Ra'anana"),
    "yavne": ("IL", "IL-TA", "Yavne"), "kfar saba": ("IL", "IL-TA", "Kfar Saba"),
    "netanya": ("IL", "IL-TA", "Netanya"), "yokneam": ("IL", "IL-HA", "Yokneam"),
    "beer sheva": ("IL", "IL-D", "Be'er Sheva"), "be'er sheva": ("IL", "IL-D", "Be'er Sheva"),
    "caesarea": ("IL", "IL-HA", "Caesarea"), "rehovot": ("IL", "IL-TA", "Rehovot"),
    "hod hasharon": ("IL", "IL-TA", "Hod Hasharon"), "bnei brak": ("IL", "IL-TA", "Bnei Brak"),
}
_US_CITIES = {
    city.lower(): ("US", f"US-{state}", city)
    for state, cities in {
        "CA": ("San Francisco", "Los Angeles", "Cupertino", "Walnut Creek", "Hawthorne", "Fremont", "Mountain View", "Sunnyvale", "Calabasas"),
        "NY": ("New York", "Medina", "Albany", "Brooklyn"), "WA": ("Seattle", "Redmond", "Bellevue"),
        "TX": ("Bastrop", "San Antonio", "Austin"), "FL": ("Tampa", "Jacksonville", "Miami"),
        "IL": ("Chicago", "Deer Park", "Lisle"), "VA": ("McLean", "Reston"),
        "OH": ("Celina", "West Chester", "Dayton"), "PA": ("Philadelphia", "Williamsport", "Lititz", "Linden", "Wayne"),
        "MI": ("Rochester Hills", "Whitehall", "Troy"), "WI": ("Pound", "Madison"),
        "CO": ("Denver", "Colorado Springs"), "MA": ("Cambridge", "Boston"), "MN": ("Maple Plain",),
        "CT": ("Greenwich",), "AR": ("Conway",), "IN": ("Fortville",), "GA": ("Atlanta",),
        "NC": ("Charlotte",), "NJ": ("South Plainfield",), "WY": ("Cheyenne",), "SC": ("Aiken",),
        "TN": ("Memphis",), "VT": ("South Burlington",), "AZ": ("Scottsdale",), "MD": ("Columbia",),
        "DC": ("Washington",),
    }.items()
    for city in cities
}
_US_STATE_CODES = frozenset({"AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY", "DC"})
_METROS = {
    "san francisco bay area": ("US", "US-CA", "San Francisco"),
    "new york city metropolitan area": ("US", "US-NY", "New York"),
    "greater cleveland": ("US", "US-OH", "Cleveland"), "greater chicago area": ("US", "US-IL", "Chicago"),
    "austin, texas metropolitan area": ("US", "US-TX", "Austin"),
    "san antonio, texas metropolitan area": ("US", "US-TX", "San Antonio"),
    "columbia, south carolina metropolitan area": ("US", "US-SC", "Columbia"),
}
_COUNTRIES = {"israel": ("IL", None, None), "il": ("IL", None, None), "united states": ("US", None, None), "united states of america": ("US", None, None), "usa": ("US", None, None), "u.s.": ("US", None, None), "u.s.a.": ("US", None, None), "us": ("US", None, None)}


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _key(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("’", "'").strip().lower())


def _split_locations(value: str) -> list[str]:
    return [part.strip() for part in re.split(r"\s*(?:;|\||·|\n)\s*|\s+/\s+", value) if part.strip()]


def _resolve_location(value: str) -> tuple[str, str | None, str | None] | None:
    key = _key(value)
    combined = _ISRAEL | _US_CITIES | _METROS | _COUNTRIES
    if key in combined:
        return combined[key]
    match = re.fullmatch(r"([^,]+),\s*([A-Z]{2})", value.strip())
    if match and match[2] in _US_STATE_CODES:
        country = _COUNTRIES.get(_key(match[1]))
        if country is not None and country[0] == "US":
            return (country[0], f"US-{match[2]}", None)
        return ("US", f"US-{match[2]}", match[1].strip())
    for alias, result in sorted((_ISRAEL | _US_CITIES | _METROS).items(), key=lambda item: len(item[0]), reverse=True):
        if re.search(rf"(?<![a-z]){re.escape(alias)}(?![a-z])", key):
            return result
    for alias, result in _COUNTRIES.items():
        if re.search(rf"(?<![a-z]){re.escape(alias)}(?![a-z])", key):
            return result
    return None


def _seniority(value: object) -> str | None:
    text = _text(value)
    if re.search(r"\b(?:intern|internship)\b", text, re.I):
        return "intern"
    if re.search(r"\b(?:junior|jr\.?|graduate|entry(?:[- ]level)?)\b", text, re.I):
        return "junior"
    if re.search(r"\b(?:staff|principal)\b", text, re.I):
        return "staff_principal"
    if re.search(r"\b(?:lead|manager|head|director)\b", text, re.I):
        return "lead_manager"
    if re.search(r"\b(?:senior|sr\.?)\b", text, re.I):
        return "senior"
    if re.search(r"\b(?:mid(?:[- ]level)?|intermediate)\b", text, re.I):
        return "mid"
    return None


_SKILL_ALIASES = {
    "react native": "React Native", "react": "React", "react.js": "React", "reactjs": "React",
    "typescript": "TypeScript", "javascript": "JavaScript", "next.js": "Next.js", "nextjs": "Next.js",
    "node.js": "Node.js", "nodejs": "Node.js", "node js": "Node.js", "python": "Python",
    "postgres": "PostgreSQL", "postgresql": "PostgreSQL", "docker": "Docker", "k8s": "Kubernetes",
    "kubernetes": "Kubernetes", "aws": "AWS", "amazon web services": "AWS", "azure": "Azure",
    "microsoft cloud": "Azure", "gcp": "GCP", "google cloud": "GCP", "golang": "Go", "go": "Go",
    "java": "Java", "vue": "Vue", "vue.js": "Vue", "angular": "Angular", "c#": "C#", "c++": "C++",
    "mongodb": "MongoDB", "redis": "Redis", "kafka": "Kafka", "elasticsearch": "Elasticsearch",
    "terraform": "Terraform", "github actions": "GitHub Actions", "linux": "Linux", ".net": ".NET",
    "dotnet": ".NET", "sql server": "SQL Server", "sql": "SQL", "php": "PHP", "ruby": "Ruby",
    "rails": "Rails", "kotlin": "Kotlin", "rust": "Rust", "scala": "Scala", "bash": "Bash",
    "fastapi": "FastAPI", "django": "Django", "spring": "Spring", "spring boot": "Spring",
    "spring framework": "Spring", "express": "Express", "express.js": "Express", "graphql": "GraphQL",
}
_SKILL_PATTERNS = (
    ("React Native", re.compile(r"\breact\s+native\b", re.I)), ("React", re.compile(r"\breact(?:\.?js)?\b(?!\s+native\b)", re.I)),
    ("TypeScript", re.compile(r"\btypescript\b", re.I)), ("JavaScript", re.compile(r"\bjavascript\b", re.I)),
    ("Next.js", re.compile(r"\bnext\.?js\b", re.I)), ("Node.js", re.compile(r"\bnode\.?js\b", re.I)),
    ("Python", re.compile(r"\bpython\b", re.I)), ("PostgreSQL", re.compile(r"\bpostgres(?:ql)?\b", re.I)),
    ("Docker", re.compile(r"\bdocker\b", re.I)), ("Kubernetes", re.compile(r"\b(?:kubernetes|k8s)\b", re.I)),
    ("AWS", re.compile(r"\b(?:aws|amazon web services)\b", re.I)), ("Azure", re.compile(r"\b(?:azure|microsoft cloud)\b", re.I)),
    ("GCP", re.compile(r"\b(?:gcp|google cloud(?: platform)?)\b", re.I)),
    ("Go", re.compile(r"\bgolang\b|\b(?:experience|proficiency|expertise|development)\s+(?:with|in|using)\s+go\b|\b(?:tech(?:nology)?\s+stack|programming\s+languages?|languages?)\s*:?[^.\n]{0,80}\bgo\b|(?:^|[,;/|])\s*go\s*(?=\s*(?:[,);/|]|$))", re.I | re.M)),
    ("Java", re.compile(r"\bjava\b", re.I)), ("Vue", re.compile(r"\bvue(?:\.js|js)?\b", re.I)),
    ("Angular", re.compile(r"\bangular\b", re.I)), ("C#", re.compile(r"\bc#(?=\W|$)", re.I)), ("C++", re.compile(r"\bc\+\+(?=\W|$)", re.I)),
    ("MongoDB", re.compile(r"\bmongodb\b", re.I)), ("Redis", re.compile(r"\bredis\b", re.I)), ("Kafka", re.compile(r"\bkafka\b", re.I)),
    ("Elasticsearch", re.compile(r"\belasticsearch\b", re.I)), ("Terraform", re.compile(r"\bterraform\b", re.I)),
    ("GitHub Actions", re.compile(r"\bgithub actions\b", re.I)), ("Linux", re.compile(r"\blinux\b", re.I)),
    (".NET", re.compile(r"(?:^|\W)(?:\.net|dotnet)\b", re.I)), ("SQL Server", re.compile(r"\bsql server\b", re.I)),
    ("SQL", re.compile(r"\bsql\b(?!\s+server\b)", re.I)), ("PHP", re.compile(r"\bphp\b", re.I)),
    ("Ruby", re.compile(r"\bruby\b", re.I)), ("Rails", re.compile(r"\brails\b", re.I)), ("Kotlin", re.compile(r"\bkotlin\b", re.I)),
    ("Rust", re.compile(r"\brust\b", re.I)), ("Scala", re.compile(r"\bscala\b", re.I)), ("Bash", re.compile(r"\bbash\b", re.I)),
    ("FastAPI", re.compile(r"\bfastapi\b", re.I)), ("Django", re.compile(r"\bdjango\b", re.I)),
    ("Spring", re.compile(r"\bspring boot\b|\bspring framework\b|\bjava(?:\s+and|[,/])?\s+spring\b|\bspring\b(?=[,)]\s+(?:and\s+)?related technologies)", re.I)),
    ("Express", re.compile(r"\bexpress(?:\.js|js)\b|\bexpress framework\b|\bnode\.?js\s*/\s*express\b|\busing express\b", re.I)),
    ("GraphQL", re.compile(r"\bgraphql\b", re.I)),
)


def _canonical_skill(value: object) -> str:
    text = _text(value)
    return _SKILL_ALIASES.get(_key(text), text)


def link_status(value: object) -> str:
    if value is None or value == "":
        return "no_link"
    try:
        parsed = urlsplit(value)
        if (parsed.scheme in {"https", "http"} and parsed.hostname and not parsed.username
                and not parsed.password and not any(char.isspace() for char in value)):
            parsed.port
            return "available"
    except (TypeError, ValueError, AttributeError):
        pass
    return "invalid_url"


@dataclass(frozen=True)
class Facts:
    countries: tuple[str, ...]
    regions: tuple[str, ...]
    cities: tuple[str, ...]
    work_mode: str
    seniority_level: str | None
    seniority_source: str | None
    skills_mentioned: tuple[str, ...]
    link_status: str
    unresolved_locations: tuple[str, ...] = ()
    normalizer_version: str = NORMALIZER_VERSION
    facts_sha256: str = field(init=False)

    def normalized_output(self) -> dict[str, object]:
        return {
            "countries": list(self.countries), "regions": list(self.regions), "cities": list(self.cities),
            "work_mode": self.work_mode, "seniority_level": self.seniority_level,
            "seniority_source": self.seniority_source, "skills_mentioned": list(self.skills_mentioned),
            "link_status": self.link_status,
        }

    def record(self) -> dict[str, object]:
        return {**self.normalized_output(), "normalizer_version": self.normalizer_version, "facts_sha256": self.facts_sha256}

    def __post_init__(self) -> None:
        encoded = json.dumps(self.normalized_output(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        object.__setattr__(self, "facts_sha256", hashlib.sha256(encoded.encode("utf-8")).hexdigest())


def normalize(posting_row: Mapping[str, object]) -> Facts:
    if not isinstance(posting_row, Mapping):
        raise TypeError("posting_row must be a mapping")
    raw_location = _text(posting_row.get("location"))
    countries: list[str] = []
    regions: list[str] = []
    cities: list[str] = []
    unresolved: list[str] = []
    for location in _split_locations(raw_location):
        resolved = _resolve_location(location)
        if resolved is None:
            if _key(location) in {"remote", "hybrid", "onsite", "on-site", "worldwide", "anywhere"}:
                continue
            unresolved.append(location)
            continue
        country, region, city = resolved
        if country and country not in countries:
            countries.append(country)
        if region and region not in regions:
            regions.append(region)
        if city and city not in cities:
            cities.append(city)
    remote_value = posting_row.get("remote")
    if remote_value is True or re.search(r"\bremote\b", raw_location, re.I):
        work_mode = "remote"
    elif re.search(r"\bhybrid\b", raw_location, re.I):
        work_mode = "hybrid"
    else:
        work_mode = "onsite"

    extracted = posting_row.get("seniority")
    if _text(extracted):
        seniority_level, seniority_source = _seniority(extracted), "extracted"
    elif any(_text(posting_row.get(key)) for key in ("ats_seniority", "ats_level")):
        seniority_level = _seniority(posting_row.get("ats_seniority") or posting_row.get("ats_level"))
        seniority_source = "ats"
    else:
        seniority_level, seniority_source = _seniority(posting_row.get("title")), "title"
        if seniority_level is None:
            seniority_source = None

    skills: list[str] = []
    seen_skills: set[str] = set()
    for item in posting_row.get("stack") or ():
        skill = _canonical_skill(item)
        if skill and _key(skill) not in seen_skills:
            skills.append(skill)
            seen_skills.add(_key(skill))
    raw_jd = _text(posting_row.get("raw_jd"))
    for name, pattern in _SKILL_PATTERNS:
        if pattern.search(raw_jd) and _key(name) not in seen_skills:
            skills.append(name)
            seen_skills.add(_key(name))
    apply_url = posting_row.get("apply_url")
    link = apply_url if apply_url not in (None, "") else posting_row.get("url")
    return Facts(tuple(countries), tuple(regions), tuple(cities), work_mode, seniority_level,
                 seniority_source, tuple(skills), link_status(link), tuple(unresolved))


__all__ = ["Facts", "LINK_STATUSES", "NORMALIZER_VERSION", "link_status", "normalize"]
