#!/usr/bin/env python3
"""Harvest recent public LinkedIn job cards without credentials."""

from __future__ import annotations

import argparse
import html
import importlib.util
import json
import logging
import os
import random
import re
import sys
import time
from datetime import date, datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo


ANNOTATION_BUDGET_SECONDS = 300.0
JD_FETCH_DEGRADED_WARNING = (
    "JD fetch degraded: more than 50% of attempted full-JD fetches failed."
)
POSITIVE_RULES: tuple[tuple[str, re.Pattern[str], int], ...] = (
    ("typescript", re.compile(r"\btypescript\b", re.I), 3),
    ("react", re.compile(r"\breact(?:\.js|js)?\b", re.I), 3),
    ("node", re.compile(r"\bnode(?:\.js|js)?\b", re.I), 2),
    ("next.js", re.compile(r"\bnext(?:\.js|js)\b", re.I), 3),
    ("full-stack", re.compile(r"\bfull[\s-]?stack\b", re.I), 4),
    ("genai", re.compile(r"\b(?:genai|generative[\s-]+ai)\b", re.I), 3),
    ("ai", re.compile(r"(?<![a-z])ai(?![a-z])", re.I), 2),
    ("agents", re.compile(r"\bagents?\b", re.I), 3),
    ("llm", re.compile(r"\bllms?\b", re.I), 3),
    ("mcp", re.compile(r"\bmcp\b", re.I), 3),
)
AI_BONUS_LABELS = {"genai", "ai", "agents", "llm", "mcp"}
AI_PROFILE_FIT_TERMS = {"ai-engineer", "llm-engineer", "agents"}
CORE_STACK_LABELS = {
    "typescript", "react", "node", "next.js", "full-stack",
    "frontend", "fullstack", "fullstack-ui",
}
CORE_STACK_PATTERN = re.compile(
    r"\b(?:typescript|react(?:\.js|js)?|node(?:\.js|js)?|next(?:\.js|js)|"
    r"full[\s-]?stack|front[\s-]?end)\b",
    re.I,
)
HARD_TITLE_EXCLUSION_PATTERN = re.compile(
    r"\bembedded\b|\bmechanical\b|\bdata[\s-]+scien(?:ces?|tists?)\b",
    re.I,
)
ROLE_TYPE_NEGATIVE_LABELS = {
    "data-scientist", "algorithm-engineer", "ml-engineer",
    "research-engineer", "computer-vision", "nlp-researcher",
    "qa-only", "team-lead", "engineering-manager", "tech-lead",
    "part-time", "student", "intern",
}

TITLE_ONLY = "title-only"
FULL_TEXT = "full-text"
NEGATIVE_RULES: tuple[tuple[str, re.Pattern[str], int, str], ...] = (
    ("staff", re.compile(r"\bstaff\b", re.I), -8, TITLE_ONLY),
    ("principal", re.compile(r"\bprincipal\b", re.I), -8, TITLE_ONLY),
    ("embedded", re.compile(r"\bembedded\s+(?:(?:c\+\+|systems?|software|firmware)\s+)?(?:systems?|software|firmware|engineer(?:ing)?|development)\b", re.I), -8, FULL_TEXT),
    ("c++", re.compile(r"(?<!\w)c\+\+(?!\w)", re.I), -8, FULL_TEXT),
    ("java-only", re.compile(r"\bjava[\s-]+only\b|\bjava\s+(?:developer|engineer)\b", re.I), -8, FULL_TEXT),
    ("data-scientist", re.compile(r"\bdata\s+scientists?\b", re.I), -12, TITLE_ONLY),
    ("algorithm-engineer", re.compile(r"\balgorithm\s+engineers?\b", re.I), -12, TITLE_ONLY),
    ("ml-engineer", re.compile(r"\b(?:ml|machine\s+learning)\s+engineers?\b", re.I), -12, TITLE_ONLY),
    ("research-engineer", re.compile(r"\bresearch\s+engineers?\b", re.I), -12, TITLE_ONLY),
    ("computer-vision", re.compile(r"\bcomputer[\s-]+vision\b", re.I), -12, TITLE_ONLY),
    ("nlp-researcher", re.compile(r"\bnlp\s+researchers?\b", re.I), -12, TITLE_ONLY),
    ("qa-only", re.compile(r"\bquality\s+engineers?\b|\bqa[\s-]+only\b|\bqa\s+(?:automation\s+)?(?:developers?|engineers?)\b", re.I), -12, TITLE_ONLY),
    ("team-lead", re.compile(r"\bteam\s+lead(?:er)?s?\b", re.I), -12, TITLE_ONLY),
    ("engineering-manager", re.compile(r"\bengineering\s+managers?\b", re.I), -12, TITLE_ONLY),
    ("tech-lead", re.compile(r"\btech(?:nical)?\s+leads?\b", re.I), -12, TITLE_ONLY),
    ("part-time", re.compile(r"\bpart[\s-]?time\b", re.I), -12, TITLE_ONLY),
    ("student", re.compile(r"\bstudents?\b", re.I), -12, TITLE_ONLY),
    ("intern", re.compile(r"\bintern(?:ship)?s?\b", re.I), -12, TITLE_ONLY),
    # Generic defaults treat non-target stacks and domains as negative signals.
    (".net", re.compile(r"(?<!\w)\.net\b|\basp\.net\b|\bdotnet\b", re.I), -8, FULL_TEXT),
    ("c#", re.compile(r"(?<!\w)c#", re.I), -8, FULL_TEXT),
    ("angular", re.compile(r"\bangular(?:js)?\b", re.I), -6, FULL_TEXT),
    ("vue", re.compile(r"\bvue(?:\.js)?\b", re.I), -6, FULL_TEXT),
    ("semiconductor/eda", re.compile(r"\bsemiconductors?\b|(?<![a-z])eda(?![a-z])", re.I), -10, FULL_TEXT),
    ("verification", re.compile(r"\b(?:hardware|silicon|design|functional)\s+verification\b|\bverification\s+(?:engineer(?:ing)?)\b", re.I), -6, FULL_TEXT),
    ("react-native", re.compile(r"\breact[\s-]native\b", re.I), -4, FULL_TEXT),
)
YEARS_REQUIREMENT_PATTERN = re.compile(
    r"\b(?:(?:minimum(?:\s+of)?|at\s+least)\s+)?"
    r"(?P<minimum>\d{1,2})\s*(?:\+|-\s*\d{1,2}|\s+or\s+more)?\s+years?\b",
    re.I,
)
YEAR_BANDS: tuple[tuple[int, str, int], ...] = (
    (10, "10+ years", -12),
    (8, "8-9+ years", -10),
    (5, "5-7+ years", -4),
)

SENIOR_TITLE_PATTERN = re.compile(r"\b(?:senior|staff|principal|lead)\b", re.I)
LOGGER = logging.getLogger("coach.jobfeed")
GUEST_SEARCH_ENDPOINT = (
    "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
)
GUEST_JOB_ENDPOINT = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting"
USER_AGENT = "Mozilla/5.0 (compatible; JobRadarCoach/1.0)"
SOURCE_ORDER = ("linkedin", "comeet", "greenhouse", "lever", "workable")
NATIVE_ATS_SOURCES = frozenset(SOURCE_ORDER[1:])
PostingIdentity = tuple[str, str]
STAFFING_COMPANIES = frozenset(
    {"medulla", "gotfriends", "got friends", "ethosia", "talent hr", "talenthr", "mertens"}
)
HEADHUNTER_SIGNAL_PATTERN = re.compile(
    r"\b(?:head[\s-]?hunter|executive\s+search|specialist\s+search|discreet\s+search|"
    r"confidential\s+(?:search|role|position|opportunity|mandate))\b",
    re.I,
)
STAFFING_SIGNAL_PATTERN = re.compile(
    r"\b(?:staffing\s+(?:agency|company)|recruit(?:ing|ment)\s+(?:agency|company)|"
    r"(?:for|on\s+behalf\s+of)\s+our\s+client|our\s+client\s+is|client\s+of\s+ours)\b|"
    r"החברה\s+המגייסת|לקוח\s+שלנו",
    re.I,
)
SOURCE_LABELS = {
    "linkedin": "LinkedIn",
    "comeet": "Comeet",
    "greenhouse": "Greenhouse",
    "lever": "Lever",
    "workable": "Workable",
}
OUTPUT_FIELDS = (
    "id",
    "title",
    "company",
    "location",
    "url",
    "posted_ago",
    "updated_at",
    "harvested_at",
    "score",
    "score_title",
    "jd_fetched",
    "jd_chars",
    "fetch_method",
    "senior_titled",
    "matched_keywords",
    "negative_hits",
    "core_stack_present",
    "ai_bonus_gated",
    "employer_class",
    "employer_class_note",
    "alive",
    "liveness_status",
    "liveness_reason",
    "liveness_final_url",
    "liveness_checked_at",
)
OUTPUT_DEFAULTS: dict[str, object] = {
    "updated_at": "",
    "score_title": 0,
    "jd_fetched": False,
    "jd_chars": 0,
    "fetch_method": "",
    "negative_hits": [],
    "core_stack_present": False,
    "ai_bonus_gated": False,
    "employer_class": "unknown",
    "employer_class_note": "",
    "alive": None,
    "liveness_status": None,
    "liveness_reason": "not-checked",
    "liveness_final_url": "",
    "liveness_checked_at": "",
}
LUNA_FIELDS = (
    "employer_type", "seniority_real", "fit_score", "fit_tier",
    "recommendation", "reasons", "fit_line", "fit_line_evidence_ids",
    "luna_status",
)
LEGACY_LUNA_FIELDS = ("employer_type", "seniority_real", "fit_line", "luna_status")
LUNA_UNAVAILABLE: dict[str, object] = {
    "employer_type": "unknown",
    "seniority_real": None,
    "fit_score": 0,
    "fit_tier": "weak",
    "recommendation": "review",
    "reasons": [],
    "fit_line": "",
    "fit_line_evidence_ids": [],
    "luna_status": "unavailable",
}
LUNA_INVALID: dict[str, object] = {
    "employer_type": "unknown",
    "seniority_real": None,
    "fit_score": 0,
    "fit_tier": "weak",
    "recommendation": "review",
    "reasons": [],
    "fit_line": "",
    "fit_line_evidence_ids": [],
    "luna_status": "invalid",
}
CONTEXTUAL_STACK_LABELS = {".net", "c#", "c++", "angular", "vue"}
OPTIONAL_REQUIREMENT_PATTERN = re.compile(
    r"\b(?:advantage|nice[\s-]+to[\s-]+have|a\s+plus|preferred|optional)\b",
    re.I,
)
INFRA_WALL_PATTERNS = {
    "docker": (re.compile(r"\bdocker\b", re.I), -8),
    "kubernetes": (re.compile(r"\b(?:kubernetes|k8s)\b", re.I), -8),
    "terraform": (re.compile(r"\bterraform\b", re.I), -8),
    "helm": (re.compile(r"\bhelm\b", re.I), -8),
}
INFRA_REQUIRED_PATTERN = re.compile(
    r"\b(?:strong\s+familiarity|hands[\s-]+on\s+experience|experience\s+(?:with|using)|"
    r"proficien\w*|required|requirements?|must|containeri[sz]ation|infrastructure\s+as\s+code)\b",
    re.I,
)
PYTHON_PRIMARY_PATTERN = re.compile(
    r"\b(?:strong|deep|advanced|expert)\s+(?:\w+\s+){0,3}(?:in\s+)?python\b|"
    r"\b(?:proficien\w*|expertise|focus)\s+(?:\w+\s+){0,3}(?:in|on|with)\s+python\b|"
    r"\bpython\s+(?:development|focus|expertise|proficien\w*|primary)\b|"
    r"\bprofessional\s+experience\s+programming\s+in\s+python\b",
    re.I,
)
NAMED_TECH_PATTERN = re.compile(
    r"\b(?:docker|kubernetes|k8s|terraform|helm|aws|azure|gcp|ansible|pulumi|"
    r"cloudformation|javascript|typescript|node(?:\.js)?|python|go|java|ruby|react)\b|"
    r"(?<!\w)(?:c#|\.net)(?!\w)",
    re.I,
)
INFRA_WALL_NAMES = {"docker", "kubernetes", "k8s", "terraform", "helm"}
VERDICT_TIERS = {"APPLY": 0, "REFERRAL": 1, "SKIP": 3}
UNREVIEWED_VERDICT_TIER = 2
EQUIVALENT_ALTERNATIVE_PATTERN = re.compile(
    r"\bor\s+(?:similar(?:\s+languages?)?|equivalent|comparable)\b", re.I
)
STRONG_POSITIVE_STACK_PATTERN = re.compile(
    r"\b(?:typescript|react(?:\.js|js)?|node(?:\.js|js)?|next(?:\.js|js))\b",
    re.I,
)
# Example-list markers prevent illustrative technology lists from becoming hard requirements.
# an example-list marker ("frameworks such as React, Angular, Vue.js") introducing an
# enumeration that also names a CORE stack term means the enumeration is illustrative,
# not a requirement — the non-core term inside it should not be penalized.
EXAMPLE_LIST_MARKER_PATTERN = re.compile(
    r"\b(?:such\s+as|for\s+example|including)\b|"
    # "one of React, Angular" / "one of the following" — not "one of our Angular
    # developers also uses React", which is a real requirement.
    r"\bone\s+of(?:\s+the\s+following)?\b(?!\s+(?:our|the|these|those|its|their|your|my)\b)|"
    # "like" is also a common verb ("we like C++ engineers with React"). Only
    # treat it as a list introducer after an example-noun ("technologies like").
    r"\b(?:frameworks?|technolog(?:y|ies)|languages?|librar(?:y|ies)|tools?|"
    r"stacks?|platforms?|systems?|options?|skills?|examples?|things?)\s+like\b|"
    # "e.g." ends in punctuation, not a word char, so it gets no trailing \b —
    # a trailing \b there can never match (punctuation + following space are
    # both non-word, so there is no boundary to anchor on).
    r"\be\.g\.|"
    # Hebrew introducers only. "או" is "or" — a list *connector*, not a marker;
    # treating it as one made the last "או" steal the list so "כמו React או
    # Angular" failed to waive Angular (core sat *before* that marker).
    r"\bכגון\b|\bכמו\b|\bלדוגמה\b",
    re.I,
)
# Glue + other list items allowed *between* a waived term and a CORE sibling.
# Arbitrary clause words ("engineers with", "developers also uses") are not
# glue — those mean the CORE mention is not in the same enumeration.
EXAMPLE_LIST_ITEM_PATTERN = re.compile(
    r"\b(?:typescript|javascript|python|java|golang|go|ruby|php|swift|kotlin|"
    r"svelte|ember|backbone|jquery|lit|solid(?:js)?|qwik|"
    r"react(?:\.js|js)?|node(?:\.js|js)?|next(?:\.js|js)|"
    r"angular(?:js)?|vue(?:\.js)?|dotnet|c(?:\+\+|#)?)\b|(?<!\w)\.net\b",
    re.I,
)
EXAMPLE_LIST_GLUE_PATTERN = re.compile(
    r"(?:,|/|;|:|\(|\)|\band\b|\bor\b|\band/or\b|\bאו\b|\s)+",
    re.I,
)
SENTENCE_BOUNDARY_PATTERN = re.compile(
    r"[;\n•]|(?<!e\.g)[.!?](?=\s+[A-Z]|\s*$)", re.I
)
# Deterministic stop-list marking where a comma/and/or/slash-joined enumeration
# ends and the surrounding sentence resumes (e.g. "...React, Angular, and Vue
# ARE supported" — "are" ends the list). Prevents a later, separately-required
# mention in the same sentence from riding the earlier waiver.
ENUMERATION_STOP_PATTERN = re.compile(
    r"\b(?:are|is|was|were|for|that|which|but|however|though|although|when|"
    r"while|required|require[sd]?|mandatory|must|needs?|only|not|depending)\b",
    re.I,
)
SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
JD_FETCH_PATH = SCRIPT_DIR / "jd_fetch.py"


def _clean_text(parts: list[str]) -> str:
    return " ".join(" ".join(parts).split())


class _LinkedInCardParser(HTMLParser):
    """Extract the stable semantic fields from LinkedIn guest-search cards."""

    FIELD_CLASSES = {
        "base-search-card__title": "title",
        "base-search-card__subtitle": "company",
        "job-search-card__location": "location",
        "job-posting-benefits__text": "benefit",
        "job-search-card__listdate": "posted_ago",
        "job-search-card__listdate--new": "posted_ago",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.postings: list[dict[str, str]] = []
        self.card: dict[str, object] | None = None
        self.card_div_depth = 0
        self.captures: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {key: value or "" for key, value in attrs}
        classes = set(attributes.get("class", "").split())

        if tag == "div" and "job-search-card" in classes and self.card is None:
            urn = attributes.get("data-entity-urn", "")
            match = re.search(r"jobPosting:(\d+)", urn)
            self.card = {"id": match.group(1) if match else "", "parts": {}}
            self.card_div_depth = 1
        elif self.card is not None and tag == "div":
            self.card_div_depth += 1

        if self.card is None:
            return

        if tag == "a" and "base-card__full-link" in classes:
            self.card["url"] = attributes.get("href", "").split("?", 1)[0]

        for class_name, field in self.FIELD_CLASSES.items():
            if class_name in classes:
                self.captures.append((tag, field))
                break

    def handle_data(self, data: str) -> None:
        if self.card is None or not self.captures or not data.strip():
            return
        field = self.captures[-1][1]
        parts = self.card["parts"]
        assert isinstance(parts, dict)
        parts.setdefault(field, []).append(data)

    def handle_endtag(self, tag: str) -> None:
        if self.card is None:
            return

        if self.captures and self.captures[-1][0] == tag:
            self.captures.pop()

        if tag == "div":
            self.card_div_depth -= 1
            if self.card_div_depth == 0:
                self._finish_card()

    def _finish_card(self) -> None:
        assert self.card is not None
        parts = self.card.pop("parts")
        assert isinstance(parts, dict)
        fields = {name: _clean_text(values) for name, values in parts.items()}
        posting = {
            "id": str(self.card.get("id", "")),
            "title": fields.get("title", ""),
            "company": fields.get("company", ""),
            "location": fields.get("location", ""),
            "url": str(self.card.get("url", "")),
            "posted_ago": fields.get("posted_ago", ""),
        }
        visible = [
            posting["title"],
            posting["company"],
            posting["location"],
            fields.get("benefit", ""),
            posting["posted_ago"],
        ]
        posting["raw_text"] = " ".join(value for value in visible if value)
        if posting["id"] and posting["title"] and posting["url"]:
            self.postings.append(posting)
        self.card = None
        self.captures.clear()


def parse_job_cards(markup: str) -> list[dict[str, str]]:
    parser = _LinkedInCardParser()
    parser.feed(markup)
    parser.close()
    return parser.postings


class _LinkedInJobDescriptionParser(HTMLParser):
    """Extract text from the semantic description container on a guest job page."""

    TARGET_CLASS = "show-more-less-html__markup"

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.capture_depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {key: value or "" for key, value in attrs}
        classes = set(attributes.get("class", "").split())
        if tag == "div" and self.capture_depth:
            self.capture_depth += 1
        elif tag == "div" and self.TARGET_CLASS in classes:
            self.capture_depth = 1

    def handle_data(self, data: str) -> None:
        if self.capture_depth and data.strip():
            self.parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "div" and self.capture_depth:
            self.capture_depth -= 1


def parse_job_description(markup: str) -> str | None:
    parser = _LinkedInJobDescriptionParser()
    parser.feed(markup)
    parser.close()
    description = _clean_text(parser.parts)
    return description or None


# Existing scoring flow is retained from source relocation; debt is tracked.
def _score_candidate(  # skipcq: PY-R1000
    title: str,
    text: str,
    profile_fit_terms: set[str] | None = None,
) -> tuple[int, list[str], list[str], bool, bool]:
    score = 0
    matches: list[str] = []
    negative_hits: list[str] = []
    has_core_stack = CORE_STACK_PATTERN.search(text) is not None
    role_type_penalty_applied = False

    for label, pattern, weight in POSITIVE_RULES:
        if pattern.search(text):
            matches.append(label)
            if label in AI_BONUS_LABELS and not has_core_stack:
                continue
            score += weight

    for label, pattern, weight, scope in NEGATIVE_RULES:
        haystack = title if scope == TITLE_ONLY else text
        occurrences = list(pattern.finditer(haystack))
        if not occurrences:
            continue
        live_occurrences: list[re.Match[str]] = []
        example_list_occurrences: list[re.Match[str]] = []
        for occurrence in occurrences:
            if _is_non_required_stack_context(label, haystack, occurrence):
                continue
            if _is_example_list_occurrence(haystack, occurrence):
                example_list_occurrences.append(occurrence)
            else:
                live_occurrences.append(occurrence)
        if live_occurrences:
            negative_hits.append(label)
            if label in ROLE_TYPE_NEGATIVE_LABELS:
                if not role_type_penalty_applied:
                    score += weight
                    role_type_penalty_applied = True
            else:
                score += weight
        if example_list_occurrences:
            # Trace the waived occurrence(s) instead of silently dropping them
            # so dashboards show why they weren't penalized — independent of
            # whether a separate, non-waived occurrence also counted above.
            negative_hits.append(f"{label}(example-list, waived)")

    years_hit = _score_years_requirement(text)
    if years_hit:
        label, weight = years_hit
        score += weight
        negative_hits.append(label)

    for label, weight in _score_requirement_walls(text):
        score += weight
        negative_hits.append(label)

    for term in sorted(profile_fit_terms or set()):
        if term == "general" or term in matches:
            continue
        escaped_term = re.escape(term).replace(r"\-", r"[\s-]")
        pattern = re.compile(rf"\b{escaped_term}\b", re.I)
        if pattern.search(text):
            matches.append(term)
            if term in AI_PROFILE_FIT_TERMS and not has_core_stack:
                continue
            score += 1

    ai_bonus_gated = not has_core_stack and bool(
        AI_BONUS_LABELS.intersection(matches)
        or AI_PROFILE_FIT_TERMS.intersection(matches)
    )
    return score, matches, negative_hits, has_core_stack, ai_bonus_gated


def _requirement_clause(text: str, start: int, end: int) -> str:
    """Return the bounded sentence/list fragment surrounding one requirement term."""

    boundaries = [
        match.start()
        for match in re.finditer(r"[;\n•]|[.!?](?=\s+[A-Z])", text)
    ]
    left = max((index for index in boundaries if index < start), default=-1)
    right_candidates = [index for index in boundaries if index >= end]
    right = min(right_candidates) if right_candidates else min(len(text), end + 220)
    return text[left + 1 : right].strip()


def _infra_or_list_has_claimable_alternative(clause: str) -> bool:
    """Return true when an or-list offers at least one non-wall technology."""

    for connector in re.finditer(r"\bor\b", clause, re.I):
        window = clause[max(0, connector.start() - 90) : connector.end() + 50]
        names = {
            match.group(0).casefold().removeprefix(".")
            for match in NAMED_TECH_PATTERN.finditer(window)
        }
        if names.intersection(INFRA_WALL_NAMES) and names.difference(INFRA_WALL_NAMES):
            return True
    return False


def _python_occurrence_is_named_alternative(
    clause: str, start: int, end: int
) -> bool:
    """Scope an alternative exemption to the specific Python occurrence in its list."""

    named = r"(?:javascript|typescript|node(?:\.js)?|go|java|ruby|c#|similar(?:\s+languages?)?)"
    before = clause[max(0, start - 45) : start]
    after = clause[end : min(len(clause), end + 45)]
    return bool(
        re.search(rf"{named}\s*(?:,|/|\bor\b)\s*$", before, re.I)
        or re.match(rf"\s*(?:,|/|\bor\b)\s*{named}\b", after, re.I)
    )


def _score_requirement_walls(text: str) -> list[tuple[str, int]]:
    """Find never-claim technologies only when the JD makes them primary requirements."""

    text = re.sub(r"[*_`]", "", text)
    hits: list[tuple[str, int]] = []
    for technology, (pattern, weight) in INFRA_WALL_PATTERNS.items():
        for match in pattern.finditer(text):
            clause = _requirement_clause(text, match.start(), match.end())
            if OPTIONAL_REQUIREMENT_PATTERN.search(clause):
                continue
            if _infra_or_list_has_claimable_alternative(clause):
                continue
            if INFRA_REQUIRED_PATTERN.search(clause):
                hits.append((f"infra:{technology}", weight))
                break

    for python_match in re.finditer(r"\bpython\b", text, re.I):
        clause = _requirement_clause(text, python_match.start(), python_match.end())
        if OPTIONAL_REQUIREMENT_PATTERN.search(clause):
            continue
        for primary_match in PYTHON_PRIMARY_PATTERN.finditer(clause):
            primary_python = re.search(r"\bpython\b", primary_match.group(0), re.I)
            if primary_python is None:
                continue
            occurrence_start = primary_match.start() + primary_python.start()
            occurrence_end = primary_match.start() + primary_python.end()
            if not _python_occurrence_is_named_alternative(
                clause, occurrence_start, occurrence_end
            ):
                hits.append(("python-primary", -16))
                return hits
    return hits


def _score_years_requirement(text: str) -> tuple[str, int] | None:
    """Apply one penalty using the highest stated minimum, not a range's upper end."""

    minimums = [
        int(match.group("minimum"))
        for match in YEARS_REQUIREMENT_PATTERN.finditer(text)
    ]
    if not minimums:
        return None

    highest_minimum = max(minimums)
    for threshold, label, weight in YEAR_BANDS:
        if highest_minimum >= threshold:
            return label, weight
    return None


def _is_non_required_stack_context(
    label: str, text: str, match: re.Match[str]
) -> bool:
    if label not in CONTEXTUAL_STACK_LABELS:
        return False

    before = text[max(0, match.start() - 45) : match.start()]
    after = text[match.end() : match.end() + 55]
    if OPTIONAL_REQUIREMENT_PATTERN.search(before) or OPTIONAL_REQUIREMENT_PATTERN.search(
        after
    ):
        return True

    alternative_window = text[
        max(0, match.start() - 90) : min(len(text), match.end() + 90)
    ]
    if EQUIVALENT_ALTERNATIVE_PATTERN.search(alternative_window):
        return True

    has_preferred_stack = STRONG_POSITIVE_STACK_PATTERN.search(alternative_window)
    has_alternative_connector = re.search(
        r"\b(?:or|and/or)\b", alternative_window, re.I
    )
    is_long_polyglot_list = alternative_window.count(",") >= 3
    return bool(
        has_preferred_stack and (has_alternative_connector or is_long_polyglot_list)
    )


def _sentence_span(text: str, index: int) -> tuple[int, int]:
    """Return the [start, end) bounds of the sentence containing `index`."""

    boundaries = [m.start() for m in SENTENCE_BOUNDARY_PATTERN.finditer(text)]
    left = max((boundary for boundary in boundaries if boundary < index), default=-1)
    right_candidates = [boundary for boundary in boundaries if boundary >= index]
    right = min(right_candidates) if right_candidates else len(text)
    return left + 1, right


def _is_example_list_occurrence(text: str, match: re.Match[str]) -> bool:
    """One occurrence is waived when it sits inside the specific enumeration span
    introduced by an example marker (such as / like / e.g. / for example / one of
    / including / כגון / כמו / לדוגמה) — and that same enumeration also names
    a CORE stack term (react/typescript/node/next) as a *list sibling* of the
    term, not merely somewhere later in the clause. The span is bounded on the
    right by the first word that resumes the sentence outside the list (e.g. "are",
    "but", "required"), so a second, separately-required mention later in the same
    sentence does not ride an earlier list's waiver."""

    start, end = _sentence_span(text, match.start())
    sentence = text[start:end]
    term_offset = match.start() - start

    markers_before = [
        marker
        for marker in EXAMPLE_LIST_MARKER_PATTERN.finditer(sentence)
        if marker.start() < term_offset
    ]
    if not markers_before:
        return False
    marker = markers_before[-1]

    stops_after_marker = [
        stop.start()
        for stop in ENUMERATION_STOP_PATTERN.finditer(sentence)
        if stop.start() > marker.end()
    ]
    enumeration_end = min(stops_after_marker, default=len(sentence))
    if term_offset >= enumeration_end:
        return False

    enumeration = sentence[marker.end() : enumeration_end]
    term_start = term_offset - marker.end()
    term_end = term_start + (match.end() - match.start())
    return _core_is_example_list_sibling(enumeration, term_start, term_end)


def _core_is_example_list_sibling(
    enumeration: str, term_start: int, term_end: int
) -> bool:
    """True when a CORE stack term sits in the same comma/or/and/או list as
    `enumeration[term_start:term_end]` — not in a later clause that happens to
    share an earlier example marker ("including React and then Angular
    experience is mandatory")."""

    if term_start < 0 or term_end > len(enumeration) or term_start >= term_end:
        return False
    for core in STRONG_POSITIVE_STACK_PATTERN.finditer(enumeration):
        if core.end() > term_start and core.start() < term_end:
            continue
        if core.end() <= term_start:
            between = enumeration[core.end() : term_start]
        else:
            between = enumeration[term_end : core.start()]
        remainder = EXAMPLE_LIST_ITEM_PATTERN.sub(" ", between)
        remainder = EXAMPLE_LIST_GLUE_PATTERN.sub("", remainder)
        if remainder.strip() == "":
            return True
    return False


def score_posting(
    posting: dict[str, object], profile_fit_terms: set[str] | None = None
) -> dict[str, object]:
    """Score the title and, when available, the full guest job description."""

    title = str(posting.get("title", ""))
    score_title, _, _, _, _ = _score_candidate(title, title, profile_fit_terms)
    jd_text = str(posting.get("jd_text", ""))
    jd_fetched = posting.get("jd_fetched") is True and bool(jd_text)
    if jd_fetched:
        card_text = str(posting.get("raw_text", "")) or title
        score_text = f"{card_text} {jd_text}"
    else:
        score_text = title
    score, matches, negative_hits, core_stack_present, ai_bonus_gated = _score_candidate(
        title, score_text, profile_fit_terms
    )

    return {
        "score": score,
        "score_title": score_title,
        "senior_titled": bool(SENIOR_TITLE_PATTERN.search(title)),
        "matched_keywords": matches,
        "negative_hits": negative_hits,
        "core_stack_present": core_stack_present,
        "ai_bonus_gated": ai_bonus_gated,
    }


def rescore_stored_posting(posting: dict[str, object]) -> dict[str, object]:
    """Apply the new gates to a persisted row whose raw JD is unavailable."""

    rescored = dict(posting)
    matches = {str(label) for label in posting.get("matched_keywords", [])}
    core_stack_present = bool(CORE_STACK_LABELS.intersection(matches))
    score = int(posting.get("score", 0))
    if not core_stack_present:
        weights = {label: weight for label, _pattern, weight in POSITIVE_RULES}
        score -= sum(weights.get(label, 0) for label in AI_BONUS_LABELS.intersection(matches))
        score -= len((AI_PROFILE_FIT_TERMS - AI_BONUS_LABELS).intersection(matches))

    title = str(posting.get("title", ""))
    new_negative_hits = list(posting.get("negative_hits", []))
    role_type_penalty_applied = bool(
        ROLE_TYPE_NEGATIVE_LABELS.intersection(new_negative_hits)
    )
    for label, pattern, weight, _scope in NEGATIVE_RULES:
        if label in new_negative_hits:
            continue
        if label in ROLE_TYPE_NEGATIVE_LABELS and pattern.search(title):
            if not role_type_penalty_applied:
                score += weight
                role_type_penalty_applied = True
            new_negative_hits.append(label)

    rescored.update(
        score=score,
        negative_hits=new_negative_hits,
        core_stack_present=core_stack_present,
        ai_bonus_gated=not core_stack_present
        and bool((AI_BONUS_LABELS | AI_PROFILE_FIT_TERMS).intersection(matches)),
    )
    return rescored


def format_rescore_table(
    before: list[dict[str, object]], after: list[dict[str, object]]
) -> str:
    rows = [
        "| Before | After | Title | New negative hits |",
        "|---:|---:|---|---|",
    ]
    for old, new in sorted(
        zip(before, after),
        key=lambda pair: (-int(pair[1]["score"]), str(pair[1]["title"]).casefold()),
    ):
        old_hits = set(old.get("negative_hits", []))
        new_hits = [hit for hit in new.get("negative_hits", []) if hit not in old_hits]
        rows.append(
            f"| {old['score']} | {new['score']} | {new['title']} | "
            f"{', '.join(new_hits) or '—'} |"
        )
    return "\n".join(rows)


def _persisted_posting_identity(posting: dict[str, object]) -> PostingIdentity:
    source = str(posting.get("source") or "linkedin").casefold()
    return source, str(posting.get("id", ""))


def load_prior_ids(output_dir: Path, current_date: str) -> set[PostingIdentity]:
    """Read source-qualified listing IDs from dated JSONL before today."""

    cutoff = date.fromisoformat(current_date)
    seen: set[PostingIdentity] = set()
    for path in sorted(output_dir.glob("????-??-??.jsonl")):
        try:
            feed_date = date.fromisoformat(path.stem)
        except ValueError:
            LOGGER.warning("Skipping invalid dated JSONL filename: %s", path)
            continue
        if feed_date >= cutoff:
            continue
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                posting = json.loads(line)
                identity = _persisted_posting_identity(posting)
            except (json.JSONDecodeError, AttributeError):
                LOGGER.warning("Skipping malformed JSONL row %s:%d", path, line_number)
                continue
            if identity[1]:
                seen.add(identity)
    return seen


def load_jsonl_ids(path: Path) -> set[PostingIdentity]:
    if not path.exists():
        return set()
    seen: set[PostingIdentity] = set()
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            posting = json.loads(line)
            identity = _persisted_posting_identity(posting)
        except (json.JSONDecodeError, AttributeError):
            LOGGER.warning("Skipping malformed JSONL row %s:%d", path, line_number)
            continue
        if identity[1]:
            seen.add(identity)
    return seen


def load_jsonl_postings(path: Path) -> list[dict[str, object]]:
    """Load every valid persisted row for a dated dashboard, skipping bad rows."""

    if not path.exists():
        return []
    postings: list[dict[str, object]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            posting = json.loads(line)
        except json.JSONDecodeError:
            LOGGER.warning("Skipping malformed JSONL row %s:%d", path, line_number)
            continue
        if not isinstance(posting, dict):
            LOGGER.warning("Skipping non-object JSONL row %s:%d", path, line_number)
            continue
        postings.append(posting)
    return postings


def apply_liveness_checks(
    postings: list[dict[str, object]],
    checker: Callable[[dict[str, object]], dict[str, object]],
) -> list[dict[str, object]]:
    """Attach liveness metadata without treating network uncertainty as closure."""

    checked: list[dict[str, object]] = []
    cache: dict[str, dict[str, object]] = {}
    for posting in postings:
        result = dict(posting)
        url = str(posting.get("url", ""))
        try:
            if url not in cache:
                cache[url] = checker(posting)
            evidence = cache[url]
            if not isinstance(evidence, dict) or "alive" not in evidence:
                raise ValueError("liveness checker returned an invalid result")
            result.update(evidence)
        except Exception as error:
            LOGGER.warning("Keeping listing after uncertain liveness check: %s", error)
            result.update(
                {
                    "alive": None,
                    "liveness_status": None,
                    "liveness_reason": f"checker-uncertain:{type(error).__name__}",
                    "liveness_final_url": url,
                    "liveness_checked_at": datetime.now(timezone.utc)
                    .replace(microsecond=0)
                    .isoformat()
                    .replace("+00:00", "Z"),
                }
            )
        checked.append(result)
    return checked


def _liveness_counts(postings: list[dict[str, object]]) -> dict[str, int]:
    return {
        "alive": sum(posting.get("alive") is True for posting in postings),
        "dead": sum(posting.get("alive") is False for posting in postings),
        "unknown": sum(posting.get("alive") is None for posting in postings),
    }


def refresh_recent_liveness(
    output_dir: Path,
    date_string: str,
    checker: Callable[[dict[str, object]], dict[str, object]],
    *,
    limit: int = 20,
) -> dict[str, int]:
    """Recheck the rolling seven-day top 20 and atomically mark closures."""

    current = date.fromisoformat(date_string)
    paths = [
        output_dir / f"{(current - timedelta(days=offset)).isoformat()}.jsonl"
        for offset in range(7)
    ]
    raw_by_path: dict[Path, list[str]] = {}
    candidates: list[tuple[Path, int, dict[str, object]]] = []
    for path in paths:
        if not path.exists():
            continue
        raw_lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        raw_by_path[path] = raw_lines
        for index, line in enumerate(raw_lines):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                LOGGER.warning("Preserving malformed JSONL row %s:%d", path, index + 1)
                continue
            if not isinstance(row, dict):
                LOGGER.warning("Preserving non-object JSONL row %s:%d", path, index + 1)
                continue
            if row.get("url"):
                candidates.append((path, index, row))
    candidates.sort(
        key=lambda item: (
            -_ranking_value(item[2]),
            str(item[2].get("title", "")).casefold(),
        )
    )
    selected = candidates[:limit]
    refreshed = apply_liveness_checks([item[2] for item in selected], checker)
    changed_paths: set[Path] = set()
    for (path, index, _row), checked in zip(selected, refreshed):
        raw_by_path[path][index] = (
            json.dumps(checked, ensure_ascii=False, sort_keys=False) + "\n"
        )
        changed_paths.add(path)
    for path in changed_paths:
        temporary = path.with_suffix(path.suffix + ".liveness.tmp")
        temporary.write_text("".join(raw_by_path[path]), encoding="utf-8")
        temporary.replace(path)
    return _liveness_counts(refreshed)


def load_triage_verdicts(path: Path) -> dict[str, dict[str, str]]:
    """Load the optional human-owned company verdict overlay fail-safely."""

    try:
        if not path.exists():
            return {}
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("top level must be an object")
        verdicts: dict[str, dict[str, str]] = {}
        for company, value in raw.items():
            try:
                if not isinstance(company, str) or not company.strip():
                    raise ValueError("company name must be a non-empty string")
                if not isinstance(value, dict) or set(value) != {"verdict", "reason"}:
                    raise ValueError("expected exactly verdict and reason")
                verdict = value.get("verdict")
                reason = value.get("reason")
                if (
                    verdict not in VERDICT_TIERS
                    or not isinstance(reason, str)
                    or not reason.strip()
                ):
                    raise ValueError("invalid verdict or reason")
                verdicts[company.strip().casefold()] = {
                    "verdict": str(verdict),
                    "reason": reason.strip(),
                }
            except ValueError as error:
                LOGGER.warning("Skipping invalid triage verdict entry %r: %s", company, error)
        return verdicts
    except (OSError, ValueError) as error:
        LOGGER.warning("Ignoring invalid triage verdict file %s: %s", path, error)
        return {}


def dedupe_postings(
    postings: list[dict[str, object]],
    seen_ids: set[str | PostingIdentity],
    seen_secondary_keys: dict[tuple[str, str], set[str]] | None = None,
) -> list[dict[str, object]]:
    fresh: list[dict[str, object]] = []
    # Bare IDs predate source-qualified history and can only mean LinkedIn.
    prior_identities = {
        identity if isinstance(identity, tuple) else ("linkedin", identity)
        for identity in seen_ids
    }
    encountered: set[tuple[str, str]] = set()
    encountered_secondary = {
        key: set(sources) for key, sources in (seen_secondary_keys or {}).items()
    }
    for posting in postings:
        listing_id = str(posting.get("id", ""))
        source_identity = (_posting_source(posting), listing_id)
        secondary = _posting_secondary_key(posting)
        source = _posting_source(posting)
        if (
            not listing_id
            or source_identity in prior_identities
            or source_identity in encountered
            or (
                secondary is not None
                and secondary in encountered_secondary
                and source not in encountered_secondary[secondary]
            )
        ):
            continue
        encountered.add(source_identity)
        if secondary is not None:
            encountered_secondary.setdefault(secondary, set()).add(source)
        fresh.append(posting)
    return fresh


def _normalized_identity(value: object) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", str(value).casefold()).split())


def _posting_secondary_key(posting: dict[str, object]) -> tuple[str, str] | None:
    company = _normalized_identity(posting.get("company", ""))
    title = _normalized_identity(posting.get("title", ""))
    return (company, title) if company and title else None


def _posting_source(posting: dict[str, object]) -> str:
    explicit = str(posting.get("source", "")).casefold()
    if explicit:
        return explicit
    listing_id = str(posting.get("id", ""))
    prefix = listing_id.split(":", 1)[0].casefold()
    return prefix if prefix in SOURCE_ORDER[1:] else "linkedin"


def classify_employer(posting: dict[str, object]) -> dict[str, str]:
    """Classify the posting source without filtering or consulting Luna."""

    company = _normalized_identity(posting.get("company", ""))
    text = " ".join(
        str(posting.get(field, ""))
        for field in ("company", "title", "raw_text", "jd_text")
    )
    if HEADHUNTER_SIGNAL_PATTERN.search(text):
        return {
            "employer_class": "headhunter",
            "employer_class_note": "Headhunter signal; 5-6yr gate; flagged, never filtered.",
        }
    company_tokens = company.split()
    seeded_staffing = any(
        company_tokens[index : index + len(seed.split())] == seed.split()
        for seed in STAFFING_COMPANIES
        for index in range(len(company_tokens) - len(seed.split()) + 1)
    )
    if seeded_staffing or STAFFING_SIGNAL_PATTERN.search(text):
        return {"employer_class": "staffing", "employer_class_note": ""}
    if _posting_source(posting) in NATIVE_ATS_SOURCES:
        return {"employer_class": "direct", "employer_class_note": ""}
    return {"employer_class": "unknown", "employer_class_note": ""}


def apply_employer_classification(
    postings: list[dict[str, object]],
) -> list[dict[str, object]]:
    classified: list[dict[str, object]] = []
    for posting in postings:
        result = dict(posting)
        result.update(classify_employer(posting))
        classified.append(result)
    return classified


def load_seen_secondary_keys(path: Path) -> dict[tuple[str, str], set[str]]:
    seen: dict[tuple[str, str], set[str]] = {}
    try:
        postings = load_jsonl_postings(path)
    except Exception as error:
        LOGGER.warning("Skipping cross-source persisted dedupe after read failure: %s", error)
        return seen
    for posting in postings:
        key = _posting_secondary_key(posting)
        if key is not None:
            seen.setdefault(key, set()).add(_posting_source(posting))
    return seen


def _load_job_feed_config(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def load_searches(path: Path) -> list[dict[str, str]]:
    """Load JSON-shaped YAML using the standard library only."""

    config = _load_job_feed_config(path)
    searches = config.get("searches") if isinstance(config, dict) else config
    if not isinstance(searches, list) or not searches:
        raise ValueError(f"Search config must be a non-empty list: {path}")
    required = {"keywords", "location", "recency"}
    for index, search in enumerate(searches):
        if not isinstance(search, dict) or set(search) != required:
            raise ValueError(f"Search #{index + 1} must contain exactly {sorted(required)}")
        if not all(isinstance(search[key], str) and search[key] for key in required):
            raise ValueError(f"Search #{index + 1} contains an empty value")
    return searches


def load_source_queries(
    path: Path, *, warning_sink: Callable[[str], None] | None = None
) -> dict[str, list[dict[str, str]]]:
    config = _load_job_feed_config(path)
    if not isinstance(config, dict):
        return {}
    sources = config.get("sources", {})
    if not isinstance(sources, dict):
        message = f"source registry must be an object: {path}"
        LOGGER.warning("Keeping LinkedIn feed after source config issue: %s", message)
        if warning_sink is not None:
            warning_sink(message)
        return {}
    parsed: dict[str, list[dict[str, str]]] = {}
    for name, queries in sources.items():
        if name not in SOURCE_ORDER[1:]:
            message = f"unsupported source {name!r} in {path}"
            LOGGER.warning("Keeping LinkedIn feed after source config issue: %s", message)
            if warning_sink is not None:
                warning_sink(message)
            continue
        if not isinstance(queries, list) or not all(
            isinstance(query, dict)
            and all(isinstance(key, str) and isinstance(value, str) and value for key, value in query.items())
            for query in queries
        ):
            message = f"source {name} must contain non-empty string query objects"
            LOGGER.warning("Keeping LinkedIn feed after source config issue: %s", message)
            if warning_sink is not None:
                warning_sink(message)
            continue
        parsed[name] = queries
    return parsed


def load_registry_source_queries() -> dict[str, list[dict[str, str]]]:
    """Load adapter-shaped queries from the reviewed ATS tenant registry."""
    path = SCRIPT_DIR / "source_registry.py"
    spec = importlib.util.spec_from_file_location("coach_jobfeed_source_registry", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load source registry: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.load_registry().source_queries()


def load_source_adapter(name: str):
    path = SCRIPT_DIR / "sources" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"coach_jobfeed_source_{name}", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load source adapter: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def harvest_sources(
    source_queries: dict[str, list[dict[str, str]]],
    enabled_sources: set[str],
    *,
    fetcher: Callable[[str], str | None],
    before_request: Callable[[], None],
    posting_filter: Callable[[dict[str, object]], bool] | None = None,
    fetch_counts: dict[str, int] | None = None,
) -> tuple[list[dict[str, object]], int]:
    postings: list[dict[str, object]] = []
    warnings = 0
    for name in SOURCE_ORDER[1:]:
        if name not in enabled_sources:
            continue
        try:
            adapter = load_source_adapter(name)
        except Exception as error:
            warnings += 1
            LOGGER.warning("Keeping feed after %s adapter failure: %s", name, error)
            continue
        for query in source_queries.get(name, []):
            try:
                prefilter_count = 0
                adapter_kwargs = {
                    "fetcher": fetcher,
                    "before_request": before_request,
                }
                if name == "workable" and posting_filter is not None:
                    def counted_filter(posting):
                        nonlocal prefilter_count
                        prefilter_count += 1
                        return posting_filter(posting)

                    adapter_kwargs["posting_filter"] = counted_filter
                fetched = list(adapter.fetch(query, **adapter_kwargs))
                if fetch_counts is not None:
                    fetch_counts[name] = fetch_counts.get(name, 0) + (
                        prefilter_count if prefilter_count else len(fetched)
                    )
                for posting in fetched:
                    enriched = dict(posting)
                    enriched["source"] = name
                    if query.get("source_tenant"):
                        enriched["source_tenant"] = query["source_tenant"]
                    postings.append(enriched)
            except Exception as error:
                warnings += 1
                LOGGER.warning("Keeping feed after %s seed failure: %s", name, error)
    return postings, warnings


def apply_recency_override(
    searches: list[dict[str, str]], recency: str | None
) -> list[dict[str, str]]:
    """Return independent search records using one explicit run window."""

    if recency is None:
        return [dict(search) for search in searches]
    # 2026-08-13: r604800 (7d) and r2592000 (30d) added for BACKLOG SWEEPS — one-off runs,
    # never a cron. The daily 12h/3h windows catch everything posted from now on; a deep window
    # only matters for (a) still-open roles that predate the pipeline, (b) re-mining the backlog
    # after searches.yaml keywords change. First-seen JSONL semantics dedupe automatically.
    if recency not in {"r10800", "r43200", "r604800", "r2592000"}:
        raise ValueError(f"Unsupported recency override: {recency}")
    return [{**search, "recency": recency} for search in searches]


def _title_match_tokens(value: object) -> set[str]:
    tokens = _normalized_identity(value).split()
    expanded: list[str] = []
    for token in tokens:
        if token == "fullstack":
            expanded.extend(("full", "stack"))
        elif token == "frontend":
            expanded.extend(("front", "end"))
        elif token == "backend":
            expanded.extend(("back", "end"))
        elif token == "developer":
            expanded.append("engineer")
        elif token == "web":
            expanded.append("software")
        else:
            expanded.append(token)
    joined = " ".join(expanded).replace("machine learning", "ai")
    return set(joined.split())


def _title_matches_model_scope(
    posting: dict[str, object], searches: list[dict[str, str]]
) -> bool:
    """Apply the shared configured-title inclusion, then explicit hard exclusions."""

    title = str(posting.get("title", ""))
    title_tokens = _title_match_tokens(title)
    included = any(
        _title_match_tokens(search["keywords"]) <= title_tokens for search in searches
    )
    return included and HARD_TITLE_EXCLUSION_PATTERN.search(title) is None


def _contains_normalized_phrase(text: str, phrase: str) -> bool:
    text_tokens = text.split()
    phrase_tokens = phrase.split()
    return bool(phrase_tokens) and any(
        text_tokens[index : index + len(phrase_tokens)] == phrase_tokens
        for index in range(len(text_tokens))
    )


def _location_matches(
    posting: dict[str, object],
    geography: str,
    location_terms: dict[str, object],
) -> bool:
    location = _normalized_identity(posting.get("location", ""))
    if geography.strip().casefold() == "remote":
        return posting.get("remote") is True or "remote" in location.split()
    aliases = location_terms.get(geography, [])
    terms = [geography]
    if isinstance(aliases, list):
        terms.extend(alias for alias in aliases if isinstance(alias, str))
    return any(
        _contains_normalized_phrase(location, normalized)
        for term in terms
        if (normalized := _normalized_identity(term))
    )


def _source_posting_matches(
    posting: dict[str, object],
    searches: list[dict[str, str]],
    location_terms: dict[str, object] | None = None,
) -> bool:
    title_tokens = _title_match_tokens(posting.get("title", ""))
    aliases = location_terms or {}
    return _title_matches_model_scope(posting, searches) and any(
        _title_match_tokens(search["keywords"]) <= title_tokens
        and _location_matches(posting, search["location"], aliases)
        for search in searches
    )


def filter_source_postings(
    postings: list[dict[str, object]],
    searches: list[dict[str, str]],
    location_terms: dict[str, object] | None = None,
) -> list[dict[str, object]]:
    """Apply configured title and geography scope to ATS boards.

    Native ATS freshness means first seen by this radar, enforced later by stable-id
    dedupe across dated JSONL files. LinkedIn's run window does not apply here.
    """

    matched = [
        posting
        for posting in postings
        if _source_posting_matches(posting, searches, location_terms)
    ]
    totals: dict[str, int] = {}
    kept: dict[str, int] = {}
    for posting in postings:
        source = _posting_source(posting)
        totals[source] = totals.get(source, 0) + 1
    for posting in matched:
        source = _posting_source(posting)
        kept[source] = kept.get(source, 0) + 1
    for source, total in totals.items():
        filtered = total - kept.get(source, 0)
        if filtered:
            LOGGER.info("Filtered %d of %d %s postings", filtered, total, source)
    return matched


def count_missing_source_jds(postings: list[dict[str, object]]) -> int:
    return sum(
        _posting_source(posting) != "linkedin" and posting.get("jd_fetched") is not True
        for posting in postings
    )


# Existing profile validation is retained from source relocation; debt is tracked.
def load_profile_contract(path: Path) -> dict[str, object]:  # skipcq: PY-R1000
    """Read the small subset of profile contract v1 needed by this job."""

    lines = path.read_text(encoding="utf-8").splitlines()
    version = 0
    positioning_parts: list[str] = []
    profile_fit_terms: set[str] = set()
    artifact_fit_terms: set[str] = set()
    prohibited_count = 0
    section = ""
    collecting_positioning = False
    collecting_profile_fit = False
    collecting_artifact_fit = False

    for line in lines:
        if line and not line.startswith(" "):
            collecting_positioning = False
            if line.endswith(":"):
                section = line[:-1]
                collecting_profile_fit = False
                collecting_artifact_fit = False
            elif line.startswith("contract_version:"):
                version = int(line.split(":", 1)[1].strip())

        if section == "profile" and line.startswith("  positioning:"):
            positioning_parts.append(line.split(":", 1)[1].strip())
            collecting_positioning = True
            continue
        if collecting_positioning and line.startswith("    "):
            positioning_parts.append(line.strip())
            continue
        if collecting_positioning and line.startswith("  "):
            collecting_positioning = False

        if section == "profile" and line.strip() == "fit_terms:":
            collecting_profile_fit = True
            continue
        if section == "profile" and collecting_profile_fit and line.startswith("  - "):
            profile_fit_terms.add(line[4:].strip())
            continue
        if section == "profile" and collecting_profile_fit and not line.startswith("  - "):
            collecting_profile_fit = False

        if section == "artifacts" and line.strip() == "fit:":
            collecting_artifact_fit = True
            continue
        if section == "artifacts" and collecting_artifact_fit and line.startswith("  - "):
            artifact_fit_terms.add(line[4:].strip())
            continue
        if section == "artifacts" and collecting_artifact_fit and not line.startswith("  - "):
            collecting_artifact_fit = False

        if section == "prohibited" and line.startswith("- "):
            prohibited_count += 1

    if version != 1:
        raise ValueError(f"Unsupported profile contract_version {version}: {path}")
    positioning = " ".join(positioning_parts)
    fit_terms = profile_fit_terms or artifact_fit_terms
    if not positioning or not fit_terms or prohibited_count == 0:
        raise ValueError(f"Incomplete profile contract: {path}")
    return {
        "contract_version": version,
        "positioning": positioning,
        "fit_terms": fit_terms,
        "prohibited_count": prohibited_count,
    }


def build_search_url(search: dict[str, str], start: int) -> str:
    parameters: dict[str, object] = {
        "keywords": search["keywords"],
        "location": search["location"],
        "f_TPR": search["recency"],
        "start": start,
    }
    if search["location"].strip().casefold() == "remote":
        parameters["f_WT"] = "2"
    query = urlencode(parameters)
    return f"{GUEST_SEARCH_ENDPOINT}?{query}"


def build_job_url(listing_id: object) -> str:
    return f"{GUEST_JOB_ENDPOINT}/{listing_id}"


def fetch_html(
    url: str,
    *,
    opener: Callable[..., object] = urlopen,
    sleep: Callable[[float], None] = time.sleep,
    backoffs: tuple[float, ...] = (1.0, 2.0),
    timeout: int = 20,
) -> str | None:
    """Fetch one guest page with a bounded retry budget and no credentials."""

    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html"})
    attempts = len(backoffs) + 1
    for attempt in range(attempts):
        try:
            with opener(request, timeout=timeout) as response:
                return response.read().decode("utf-8", errors="replace")
        except OSError as error:
            if attempt == attempts - 1:
                LOGGER.warning("Guest request blocked after %d attempts: %s", attempts, error)
                return None
            delay = backoffs[attempt]
            LOGGER.warning(
                "Guest request attempt %d/%d failed (%s); retrying in %.1fs",
                attempt + 1,
                attempts,
                error,
                delay,
            )
            sleep(delay)
    return None


class RequestPacer:
    """Apply a random 2-4 second gap between guest-page requests."""

    def __init__(
        self,
        *,
        sleep: Callable[[float], None] = time.sleep,
        uniform: Callable[[float, float], float] = random.uniform,
    ) -> None:
        self.sleep = sleep
        self.uniform = uniform
        self.first_request = True

    def __call__(self) -> None:
        if self.first_request:
            self.first_request = False
            return
        self.sleep(self.uniform(2.0, 4.0))


JD_FETCH_MIN_INTERVAL_SECONDS = 2.0


def fetch_job_descriptions(
    postings: list[dict[str, object]],
    *,
    fetcher: Callable[[str], dict[str, object]],
    sleep: Callable[[float], None] = time.sleep,
    max_fetches: int = 40,
) -> tuple[list[dict[str, object]], int]:
    """Fetch short LinkedIn JDs without letting one failure stop the run."""

    enriched: list[dict[str, object]] = []
    warnings = 0
    attempted = 0
    for posting in postings:
        result = dict(posting)
        existing_jd = str(posting.get("jd_text") or "").strip()
        if len(existing_jd) >= 200:
            enriched.append(result)
            continue
        if _posting_source(posting) != "linkedin":
            enriched.append(result)
            continue
        if attempted >= max_fetches:
            enriched.append(result)
            continue
        if attempted:
            sleep(JD_FETCH_MIN_INTERVAL_SECONDS)
        attempted += 1
        try:
            fetched = fetcher(str(posting.get("url", "")))
        except Exception as error:
            fetched = {
                "jd_text": "",
                "jd_chars": 0,
                "fetch_method": "failed",
                "fetch_error": str(error),
            }
        description = str(fetched.get("jd_text") or "")
        fetch_method = str(fetched.get("fetch_method") or "failed")
        if fetch_method == "guest-html" and description:
            result["jd_fetched"] = True
            result["jd_text"] = description
            result["jd_chars"] = len(description)
            result["fetch_method"] = fetch_method
        else:
            result["jd_fetched"] = False
            result["jd_chars"] = 0
            result["fetch_method"] = "failed"
            result["fetch_error"] = str(
                fetched.get("fetch_error") or "description not found"
            )
            warnings += 1
            LOGGER.warning(
                "Keeping title-only score after empty/blocked JD: %s",
                posting.get("id", ""),
            )
        enriched.append(result)
    return enriched, warnings


def jd_fetch_is_degraded(*, attempted: int, failed: int) -> bool:
    """Flag only runs where strictly more than half of attempted fetches fail."""

    # This form directly mirrors the documented "more than half failed" predicate.
    return attempted > 0 and failed * 2 > attempted  # skipcq: PYL-R1716


def append_postings(output_dir: Path, date_string: str, postings: list[dict[str, object]]) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{date_string}.jsonl"
    with path.open("a", encoding="utf-8") as handle:
        for posting in postings:
            row = {
                field: posting.get(field, OUTPUT_DEFAULTS[field])
                if field in OUTPUT_DEFAULTS
                else posting[field]
                for field in OUTPUT_FIELDS
            }
            row["source"] = _posting_source(posting)
            row["source_tenant"] = str(
                posting.get("source_tenant") or "linkedin-guest"
            )
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=False) + "\n")
    return path


def _markdown_cell(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def _posting_time_display(posting: dict[str, object]) -> str:
    """Keep publication and edit times distinct without duplicating Comeet's label."""

    posted = str(posting.get("posted_ago", "")).strip()
    updated = str(posting.get("updated_at", "")).strip()
    if not updated or posted.casefold().startswith("updated "):
        return posted
    return f"{posted} · Updated {updated}" if posted else f"Updated {updated}"


def count_postings_by_source(
    postings: list[dict[str, object]], enabled_sources: set[str] | None = None
) -> dict[str, int]:
    included = {"linkedin", *(enabled_sources or set())}
    counts = {name: 0 for name in SOURCE_ORDER if name in included}
    for posting in postings:
        source = str(posting.get("source") or "linkedin").casefold()
        if source in counts:
            counts[source] += 1
    return counts


def format_source_counts(counts: dict[str, int]) -> str:
    return " · ".join(
        f"{SOURCE_LABELS[name]} {counts[name]}"
        for name in SOURCE_ORDER
        if name in counts
    )


EMPLOYER_CLASS_LABELS = {
    "direct": "Direct",
    "staffing": "Staffing",
    "headhunter": "Headhunter",
    "unknown": "Unknown",
}
LUNA_EMPLOYER_LABELS = {
    "direct": "Direct",
    "agency": "Agency",
    "unknown": "Unknown",
}


def _employer_types_disagree(employer_class: str, employer_type: str) -> bool:
    if employer_class == "unknown" or employer_type == "unknown":
        return False
    expected_luna = {
        "direct": "direct",
        "staffing": "agency",
        "headhunter": "agency",
        "unknown": "unknown",
    }.get(employer_class)
    return bool(employer_type and expected_luna and employer_type != expected_luna)


def _employer_markdown(posting: dict[str, object]) -> str:
    employer_class = str(posting.get("employer_class", ""))
    employer_type = str(posting.get("employer_type", ""))
    if employer_class:
        if employer_class == "unknown" and employer_type in {"direct", "agency"}:
            return f"Luna only: {LUNA_EMPLOYER_LABELS[employer_type]}"
        label = EMPLOYER_CLASS_LABELS.get(employer_class, "Unknown")
        if _employer_types_disagree(employer_class, employer_type):
            luna = LUNA_EMPLOYER_LABELS.get(employer_type, "Unknown")
            return f"Rule: {label}; Luna: {luna}"
        return label
    return {
        "agency": "🏢 Agency",
        "direct": "Direct",
        "unknown": "Unknown",
    }.get(employer_type, "—")


def _employer_html(posting: dict[str, object]) -> str:
    employer_class = str(posting.get("employer_class", ""))
    employer_type = str(posting.get("employer_type", ""))
    if not employer_class:
        return {
            "agency": '<span class="pill agency">🏢 Agency</span>',
            "direct": '<span class="pill">Direct</span>',
            "unknown": '<span class="pill">Unknown</span>',
        }.get(employer_type, '<span class="muted">Luna pending</span>')
    if employer_class == "unknown" and employer_type in {"direct", "agency"}:
        luna = html.escape(LUNA_EMPLOYER_LABELS[employer_type])
        return f'<span class="fit">Luna only: {luna}</span>'
    label = EMPLOYER_CLASS_LABELS.get(employer_class, "Unknown")
    css_class = " agency" if employer_class in {"staffing", "headhunter"} else ""
    rule = f'<span class="pill{css_class}">{html.escape(label)}</span>'
    if not _employer_types_disagree(employer_class, employer_type):
        return rule
    luna = html.escape(LUNA_EMPLOYER_LABELS.get(employer_type, "Unknown"))
    return f'{rule}<span class="fit">Rule: {html.escape(label)} · Luna: {luna}</span>'


# Existing deterministic rendering flow is retained from relocation; debt is tracked.
def write_summary(  # skipcq: PY-R1000
    output_dir: Path,
    date_string: str,
    postings: list[dict[str, object]],
    *,
    harvested_count: int,
    skipped_seen: int,
    warning_count: int,
    source_counts: dict[str, int] | None = None,
    liveness_counts: dict[str, int] | None = None,
    jd_fetch_degraded: bool = False,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    postings = [posting for posting in postings if posting.get("alive") is not False]
    top = sorted(
        postings,
        key=lambda posting: (-_ranking_value(posting), str(posting["title"]).casefold()),
    )[:10]
    lines = [
        f"# Job feed — {date_string}",
        "",
    ]
    if jd_fetch_degraded:
        lines.extend(
            ["> [!WARNING]", f"> {JD_FETCH_DEGRADED_WARNING}", ""]
        )
    lines.extend([
        f"- Harvested cards: {harvested_count}",
        f"- New postings: {len(postings)}",
        f"- Previously seen: {skipped_seen}",
        f"- JD fetched: {sum(posting.get('jd_fetched') is True for posting in postings)}/{len(postings)}",
        f"- Senior-titled: {sum(bool(posting['senior_titled']) for posting in postings)}",
        f"- Warnings: {warning_count}",
    ])
    if source_counts is not None:
        lines.append(f"- Sources: {format_source_counts(source_counts)}")
    if liveness_counts is not None:
        lines.append(
            "- Liveness: "
            f"alive {liveness_counts['alive']} · dead {liveness_counts['dead']} · "
            f"unknown {liveness_counts['unknown']}"
        )
    lines.extend([
        "",
        "## Top 10 by deterministic score",
        "",
        "| Score | Title score | JD | Negative hits | Senior | Employer | Role | Company | Location | Posted |",
        "|---:|---:|:---:|---|:---:|---|---|---|---|---|",
    ])
    for posting in top:
        fit_line = _markdown_cell(posting.get("fit_line", ""))
        luna_status = str(posting.get("luna_status", ""))
        if not fit_line and luna_status in {"unavailable", "invalid"}:
            fit_line = f"Luna {luna_status}"
        employer_note = _markdown_cell(posting.get("employer_class_note", ""))
        if employer_note:
            fit_line = f"{employer_note} {fit_line}".strip()
        role = f"[{_markdown_cell(posting['title'])}]({posting['url']})"
        if fit_line:
            role += f"<br><sub>{fit_line}</sub>"
        employer = _employer_markdown(posting)
        score_title = posting.get("score_title", OUTPUT_DEFAULTS["score_title"])
        jd = "yes" if posting.get("jd_fetched") is True else "title-only"
        negative_hits = _markdown_cell(", ".join(posting.get("negative_hits", [])) or "—")
        senior = "yes" if posting["senior_titled"] else "no"
        company = _markdown_cell(posting["company"])
        location = _markdown_cell(posting["location"])
        posted = _markdown_cell(_posting_time_display(posting))
        lines.append(
            f"| {posting['score']} | {score_title} | {jd} | {negative_hits} | "
            f"{senior} | {employer} | {role} | {company} | {location} | {posted} |"
        )
    if not top:
        lines.append("| — | — | — | — | — | — | No new postings | — | — | — |")
    lines.append("")
    path = output_dir / "latest-summary.md"
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text("\n".join(lines), encoding="utf-8")
    temporary.replace(path)
    return path



# Existing annotation validation is retained from relocation; debt is tracked.
def _validated_pipeline_annotation(value: object) -> dict[str, object]:  # skipcq: PY-R1000
    if not isinstance(value, dict):
        return dict(LUNA_INVALID)
    if set(value) == set(LEGACY_LUNA_FIELDS):
        fields = LEGACY_LUNA_FIELDS
    elif set(value) == set(LUNA_FIELDS):
        fields = LUNA_FIELDS
    else:
        return dict(LUNA_INVALID)
    if value.get("employer_type") not in {"direct", "agency", "unknown"}:
        return dict(LUNA_INVALID)
    seniority_real = value.get("seniority_real")
    if seniority_real is not None and not isinstance(seniority_real, bool):
        return dict(LUNA_INVALID)
    fit_line = value.get("fit_line")
    status = value.get("luna_status")
    if fields == LUNA_FIELDS:
        fit_score = value.get("fit_score")
        if (
            isinstance(fit_score, bool)
            or not isinstance(fit_score, int)
            or not 0 <= fit_score <= 100
        ):
            return dict(LUNA_INVALID)
        if value.get("fit_tier") not in {"strong", "good", "stretch", "weak"}:
            return dict(LUNA_INVALID)
        if value.get("recommendation") not in {"apply", "referral", "review", "skip"}:
            return dict(LUNA_INVALID)
        if not isinstance(value.get("reasons"), list):
            return dict(LUNA_INVALID)
        evidence_ids = value.get("fit_line_evidence_ids")
        if not isinstance(evidence_ids, list) or not all(
            isinstance(item, str) and item for item in evidence_ids
        ):
            return dict(LUNA_INVALID)
    if not isinstance(fit_line, str) or len(fit_line) > 160:
        return dict(LUNA_INVALID)
    if status not in {"ok", "unavailable", "invalid"}:
        return dict(LUNA_INVALID)
    if status == "ok" and not fit_line.strip():
        return dict(LUNA_INVALID)
    return {field: value[field] for field in fields}


def _ranking_value(posting: dict[str, object]) -> int:
    """Use valid Luna fit when available; otherwise use deterministic score."""
    fit_score = posting.get("fit_score")
    if (
        posting.get("luna_status") == "ok"
        and isinstance(fit_score, int)
        and not isinstance(fit_score, bool)
    ):
        return fit_score
    return int(posting.get("score", 0))


def annotate_positive_postings(
    postings: list[dict[str, object]],
    annotator: Callable[[dict[str, object]], dict[str, object] | None],
    *,
    deadline: float | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> tuple[list[dict[str, object]], int, int, int]:
    """Annotate positive-scored rows without letting one call break the batch."""

    annotated: list[dict[str, object]] = []
    attempted = 0
    unavailable = 0
    invalid = 0
    for posting in postings:
        result = dict(posting)
        if int(posting.get("score", 0)) <= 0:
            annotated.append(result)
            continue
        if deadline is not None and clock() >= deadline:
            unavailable += 1
            result.update(LUNA_UNAVAILABLE)
            annotated.append(result)
            continue
        attempted += 1
        try:
            annotation = annotator(dict(posting))
        except Exception as error:
            LOGGER.warning(
                "Luna annotator crashed for %s: %s", posting.get("id", ""), error
            )
            annotation = None
        if annotation is None:
            unavailable += 1
            result.update(LUNA_UNAVAILABLE)
        else:
            validated = _validated_pipeline_annotation(annotation)
            if validated["luna_status"] == "unavailable":
                unavailable += 1
            elif validated["luna_status"] == "invalid":
                invalid += 1
            result.update(validated)
        annotated.append(result)
    return annotated, attempted, unavailable, invalid


def persist_annotations(path: Path, postings: list[dict[str, object]]) -> None:
    """Atomically add Luna fields to already-written rows, preserving base fields."""

    annotations = {
        str(posting.get("id", "")): {
            field: posting[field] for field in LUNA_FIELDS if field in posting
        }
        for posting in postings
        if any(field in posting for field in LUNA_FIELDS)
    }
    if not annotations:
        return

    rows: list[dict[str, object]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        annotation = annotations.get(str(row.get("id", "")))
        if annotation:
            row.update(annotation)
        rows.append(row)

    rows.sort(
        key=lambda row: (-_ranking_value(row), str(row.get("title", "")).casefold())
    )

    temporary = path.with_suffix(path.suffix + ".luna.tmp")
    temporary.write_text(
        "".join(
            json.dumps(row, ensure_ascii=False, sort_keys=False) + "\n" for row in rows
        ),
        encoding="utf-8",
    )
    temporary.replace(path)



def load_luna_annotator(
    profile: dict[str, object] | None = None,
) -> Callable[[dict[str, object]], dict[str, object] | None]:
    path = SCRIPT_DIR / "annotate.py"
    spec = importlib.util.spec_from_file_location("coach_jobfeed_annotate", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load Luna annotator: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if profile is None:
        return module.annotate
    return lambda posting: module.annotate(posting, profile=profile)


def load_database_module():
    path = SCRIPT_DIR / "database.py"
    spec = importlib.util.spec_from_file_location("coach_jobfeed_database", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load database helpers: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_liveness_checker() -> Callable[[dict[str, object]], dict[str, object]]:
    path = SCRIPT_DIR / "liveness.py"
    spec = importlib.util.spec_from_file_location("coach_jobfeed_liveness", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load liveness checker: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.check_posting


def load_full_jd_fetcher() -> Callable[[str], dict[str, object]]:
    spec = importlib.util.spec_from_file_location("coach_jobfeed_jd_fetch", JD_FETCH_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load JD fetcher: {JD_FETCH_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.fetch_full_jd


def _compatibility_jd_fetcher(
    fetcher: Callable[[str], str | None],
) -> Callable[[str], dict[str, object]]:
    """Keep historical offline tests on the old injected HTML fetch seam."""

    def fetch(posting_url: str) -> dict[str, object]:
        match = re.search(r"(\d+)(?:/?(?:\?.*)?)$", posting_url)
        page_html = fetcher(build_job_url(match.group(1))) if match else None
        description = parse_job_description(page_html) if page_html else None
        if not description:
            return {
                "jd_text": "",
                "jd_chars": 0,
                "fetch_method": "failed",
                "fetch_error": "description not found",
            }
        return {
            "jd_text": description,
            "jd_chars": len(description),
            "fetch_method": "guest-html",
            "fetch_error": None,
        }

    return fetch


def harvest_search(
    search: dict[str, str],
    *,
    max_pages: int,
    fetcher: Callable[[str], str | None],
    before_request: Callable[[], None],
    page_size: int = 25,
) -> tuple[list[dict[str, str]], int]:
    postings: list[dict[str, str]] = []
    warnings = 0
    for page_index in range(max_pages):
        before_request()
        page_html = fetcher(build_search_url(search, start=page_index * page_size))
        if page_html is None:
            LOGGER.warning("Skipping blocked search: %s", search["keywords"])
            warnings += 1
            break
        page = parse_job_cards(page_html)
        if not page:
            if page_index == 0:
                LOGGER.warning("Search returned no cards: %s", search["keywords"])
                warnings += 1
            break
        postings.extend(page)
        if len(page) < page_size:
            break
    return postings, warnings


# Existing orchestration flow is retained from source relocation; debt is tracked.
def run_pipeline(  # skipcq: PY-R1000
    *,
    config_path: Path,
    profile_path: Path,
    output_dir: Path,
    date_string: str,
    harvested_at: str,
    max_pages: int,
    fetcher: Callable[[str], str | None],
    before_request: Callable[[], None],
    recency_override: str | None = None,
    annotator: Callable[[dict[str, object]], dict[str, object] | None] | None = None,
    clock: Callable[[], float] = time.monotonic,
    enabled_sources: set[str] | None = None,
    jd_fetcher: Callable[[str], dict[str, object]] | None = None,
    jd_sleep: Callable[[float], None] = time.sleep,
    jd_fetch_cap: int = 40,
    liveness_checker: Callable[[dict[str, object]], dict[str, object]] | None = None,
    profile_snapshot: dict[str, object] | None = None,
    posting_writer: Callable[[list[dict[str, object]], str], object] | None = None,
) -> dict[str, object]:
    if jd_fetch_cap < 0:
        raise ValueError("jd_fetch_cap must be non-negative")

    enabled_sources = set(enabled_sources or set())
    unsupported_sources = enabled_sources.difference(SOURCE_ORDER[1:])
    if unsupported_sources:
        raise ValueError(f"Unsupported sources: {sorted(unsupported_sources)}")
    database_mode = profile_snapshot is not None or posting_writer is not None
    if profile_snapshot is None and posting_writer is not None:
        raise ValueError("DB persistence requires one complete profile snapshot")
    if profile_snapshot is not None and posting_writer is None:
        raise ValueError("DB profile mode requires a posting writer")
    if database_mode:
        database = load_database_module()
        searches = apply_recency_override(
            database.searches_from_profile(profile_snapshot), recency_override
        )
        raw_fit_terms = profile_snapshot.get("candidate.fit_terms", [])
        raw_location_terms = profile_snapshot.get("search.location_terms", {})
        if not isinstance(raw_fit_terms, list) or not isinstance(raw_location_terms, dict):
            raise ValueError("DB profile has invalid fit or geography fields")
        fit_terms = {
            term for term in raw_fit_terms if isinstance(term, str) and term.strip()
        }
        location_terms = raw_location_terms
    else:
        searches = apply_recency_override(load_searches(config_path), recency_override)
        profile = load_profile_contract(profile_path)
        fit_terms = profile["fit_terms"]
        assert isinstance(fit_terms, set)
        location_terms = {}
    source_config_warnings: list[str] = []
    if enabled_sources:
        try:
            # Retain warning-only validation for callers carrying the retired
            # inline config; dispatch is authoritative from the registry below.
            if not database_mode:
                load_source_queries(
                    config_path, warning_sink=source_config_warnings.append
                )
            source_queries = load_registry_source_queries()
        except Exception as error:
            source_queries = {}
            source_config_warnings.append(str(error))
            LOGGER.warning(
                "Keeping LinkedIn feed after source config failure: %s", error
            )
    else:
        source_queries = {}
    harvested: list[dict[str, object]] = []
    linkedin_fetched_count = 0
    linkedin_matched_count = 0
    warning_count = len(source_config_warnings)
    for search in searches:
        page_postings, page_warnings = harvest_search(
            search,
            max_pages=max_pages,
            fetcher=fetcher,
            before_request=before_request,
        )
        linkedin_fetched_count += len(page_postings)
        matched_page = [
            posting
            for posting in page_postings
            if _source_posting_matches(posting, searches, location_terms)
        ]
        linkedin_matched_count += len(matched_page)
        harvested.extend(matched_page)
        warning_count += page_warnings

    source_fetch_counts = {name: 0 for name in SOURCE_ORDER if name in enabled_sources}
    source_postings, source_warnings = harvest_sources(
        source_queries,
        enabled_sources,
        fetcher=fetcher,
        before_request=before_request,
        posting_filter=lambda posting: _source_posting_matches(
            posting, searches, location_terms
        ),
        fetch_counts=source_fetch_counts,
    )
    source_postings = filter_source_postings(
        source_postings, searches, location_terms
    )
    source_match_counts = count_postings_by_source(source_postings, enabled_sources)
    source_match_counts["linkedin"] = linkedin_matched_count
    harvested.extend(source_postings)
    warning_count += source_warnings + count_missing_source_jds(source_postings)
    fetched_count = linkedin_fetched_count + sum(source_fetch_counts.values())
    matched_count = len(harvested)

    unique = dedupe_postings(harvested, set())
    if database_mode:
        fresh = unique
    else:
        known_ids = load_prior_ids(output_dir, current_date=date_string)
        known_ids.update(load_jsonl_ids(output_dir / f"{date_string}.jsonl"))
        fresh = dedupe_postings(
            unique,
            known_ids,
            load_seen_secondary_keys(output_dir / f"{date_string}.jsonl"),
        )
    if liveness_checker is not None:
        fresh = apply_liveness_checks(fresh, liveness_checker)
    live_fresh = [posting for posting in fresh if posting.get("alive") is not False]
    dead_fresh = [posting for posting in fresh if posting.get("alive") is False]
    jd_fetch_candidates = sum(
        _posting_source(posting) == "linkedin"
        and len(str(posting.get("jd_text") or "").strip()) < 200
        for posting in live_fresh
    )
    jd_fetch_attempted = min(jd_fetch_cap, jd_fetch_candidates)
    fresh_with_jds, jd_warning_count = fetch_job_descriptions(
        live_fresh,
        fetcher=jd_fetcher or _compatibility_jd_fetcher(fetcher),
        sleep=jd_sleep,
        max_fetches=jd_fetch_cap,
    )
    jd_fetch_failed = jd_warning_count
    jd_fetch_degraded = jd_fetch_is_degraded(
        attempted=jd_fetch_attempted,
        failed=jd_fetch_failed,
    )
    warning_count += jd_warning_count

    scored_all: list[dict[str, object]] = []
    for posting in [*fresh_with_jds, *dead_fresh]:
        enriched: dict[str, object] = dict(posting)
        enriched.update(score_posting(posting, profile_fit_terms=fit_terms))
        enriched["harvested_at"] = harvested_at
        scored_all.append(enriched)
    scored_all = apply_employer_classification(scored_all)
    scored = [posting for posting in scored_all if posting.get("alive") is not False]
    source_counts = count_postings_by_source(scored_all, enabled_sources)
    liveness_counts = _liveness_counts(scored_all)

    output_path = None
    recent_liveness_counts = None
    observed_posting_ids: list[str] = []
    inserted_posting_ids: list[str] = []
    annotation_candidates = scored
    if database_mode:
        assert posting_writer is not None
        persistence = posting_writer(scored_all, harvested_at)
        if not isinstance(persistence, dict) or set(persistence) != {
            "observed_posting_ids", "inserted_posting_ids"
        }:
            raise ValueError("DB posting writer returned an invalid disposition")
        observed = persistence["observed_posting_ids"]
        inserted = persistence["inserted_posting_ids"]
        if (
            not isinstance(observed, list)
            or not isinstance(inserted, list)
            or not all(isinstance(posting_id, str) for posting_id in [*observed, *inserted])
            or len(observed) != len(scored_all)
            or not set(inserted) <= set(observed)
        ):
            raise ValueError("DB posting writer returned an invalid disposition")
        observed_posting_ids = observed
        inserted_posting_ids = inserted
        inserted_set = set(inserted_posting_ids)
        annotation_candidates = [
            posting
            for posting, posting_id in zip(scored_all, observed_posting_ids)
            if posting_id in inserted_set and posting.get("alive") is not False
        ]
    else:
        output_path = append_postings(output_dir, date_string, scored_all)
    if liveness_checker is not None and not database_mode:
        recent_liveness_counts = refresh_recent_liveness(
            output_dir, date_string, liveness_checker
        )
    skipped_seen = len(unique) - len(fresh)
    if database_mode:
        skipped_seen += len(observed_posting_ids) - len(inserted_posting_ids)
    if not database_mode:
        write_summary(
            output_dir,
            date_string,
            scored,
            harvested_count=len(harvested),
            skipped_seen=skipped_seen,
            warning_count=warning_count,
            source_counts=source_counts if enabled_sources else None,
            liveness_counts=liveness_counts if liveness_checker is not None else None,
            jd_fetch_degraded=jd_fetch_degraded,
        )
    annotated = annotation_candidates
    annotation_count = 0
    annotation_unavailable_count = 0
    annotation_invalid_count = 0
    annotation_seconds = 0.0
    if annotator is not None:
        annotation_started = clock()
        (
            annotated,
            annotation_count,
            annotation_unavailable_count,
            annotation_invalid_count,
        ) = annotate_positive_postings(
            annotation_candidates,
            annotator,
            deadline=annotation_started + ANNOTATION_BUDGET_SECONDS,
            clock=clock,
        )
        annotation_seconds = round(clock() - annotation_started, 3)
        if output_path is not None:
            try:
                persist_annotations(output_path, annotated)
                write_summary(
                    output_dir,
                    date_string,
                    annotated,
                    harvested_count=len(harvested),
                    skipped_seen=skipped_seen,
                    warning_count=warning_count,
                    source_counts=source_counts if enabled_sources else None,
                    liveness_counts=(
                        liveness_counts if liveness_checker is not None else None
                    ),
                    jd_fetch_degraded=jd_fetch_degraded,
                )
            except (OSError, ValueError) as error:
                LOGGER.warning(
                    "Keeping deterministic feed after Luna persistence failure: %s", error
                )
                annotated = scored
                annotation_unavailable_count = annotation_count
                annotation_invalid_count = 0

    result: dict[str, object] = {
        "fetched_count": fetched_count,
        "matched_count": matched_count,
        "new_count": len(inserted_posting_ids) if database_mode else len(scored_all),
        "harvested_count": len(harvested),
        "jd_fetched_count": sum(posting.get("jd_fetched") is True for posting in scored),
        "jd_fetch_attempted": jd_fetch_attempted,
        "jd_fetch_failed": jd_fetch_failed,
        "jd_fetch_degraded": jd_fetch_degraded,
        "skipped_seen": skipped_seen,
        "warning_count": warning_count,
        "annotation_count": annotation_count,
        "annotation_unavailable_count": annotation_unavailable_count,
        "annotation_invalid_count": annotation_invalid_count,
        "annotation_seconds": annotation_seconds,
    }
    if database_mode:
        inserted_set = set(inserted_posting_ids)
        result["observed_count"] = len(scored_all)
        result["observed_published_count"] = len(scored)
        result["new_published_count"] = sum(
            posting_id in inserted_set and posting.get("alive") is not False
            for posting, posting_id in zip(scored_all, observed_posting_ids)
        )
        result["observed_posting_ids"] = observed_posting_ids
        result["inserted_posting_ids"] = inserted_posting_ids
    else:
        result["new_published_count"] = len(scored)
    if enabled_sources:
        result["source_counts"] = source_counts
        result["source_fetch_counts"] = source_fetch_counts
        result["source_match_counts"] = source_match_counts
    if liveness_checker is not None:
        result["alive_count"] = liveness_counts["alive"]
        result["dead_count"] = liveness_counts["dead"]
        result["liveness_unknown_count"] = liveness_counts["unknown"]
    if recent_liveness_counts is not None:
        result["recent_liveness_counts"] = recent_liveness_counts
    return result


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Harvest recent public job postings into Postgres."
    )
    parser.add_argument(
        "--jsonl",
        action="store_true",
        help="Use the legacy local JSONL output instead of Postgres",
    )
    parser.add_argument(
        "--no-annotate",
        action="store_true",
        help="Skip optional Luna annotation for this bounded run",
    )
    parser.add_argument("--max-pages", type=int, default=5, help="Page cap per search (default: 5)")
    parser.add_argument(
        "--jd-fetch-cap",
        type=int,
        default=40,
        help="Full-JD guest-page fetch cap per run (default: 40)",
    )
    parser.add_argument("--date", help="Output date override in YYYY-MM-DD form")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=REPO_ROOT / "data" / "job-feed",
        help="Output directory",
    )
    parser.add_argument("--config", type=Path, default=SCRIPT_DIR / "searches.yaml")
    parser.add_argument(
        "--recency",
        choices=("r10800", "r43200", "r604800", "r2592000"),
        help="Override every configured search window for this run",
    )
    parser.add_argument(
        "--profile",
        type=Path,
        default=REPO_ROOT / "profile.yaml",
    )
    parser.add_argument(
        "--sources",
        default="",
        help="Comma-separated public ATS sources (disabled by default)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_argument_parser().parse_args(argv)
    if args.max_pages < 1:
        raise SystemExit("--max-pages must be at least 1")
    if args.jd_fetch_cap < 0:
        raise SystemExit("--jd-fetch-cap must be non-negative")
    enabled_sources = {name.strip().casefold() for name in args.sources.split(",") if name.strip()}
    unsupported_sources = enabled_sources.difference(SOURCE_ORDER[1:])
    if unsupported_sources:
        raise SystemExit(f"--sources contains unsupported values: {sorted(unsupported_sources)}")

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    jerusalem_now = datetime.now(ZoneInfo("Asia/Jerusalem"))
    if args.date:
        try:
            parsed_date = date.fromisoformat(args.date)
        except ValueError as error:
            raise SystemExit("--date must use YYYY-MM-DD") from error
        if parsed_date.isoformat() != args.date:
            raise SystemExit("--date must use YYYY-MM-DD")
        date_string = args.date
    else:
        date_string = jerusalem_now.date().isoformat()
    harvested_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    def unavailable_annotator(_posting: dict[str, object]) -> None:
        return None

    try:
        profile_snapshot = None
        posting_writer = None
        if args.jsonl:
            annotation_profile = None
        else:
            database_url = os.environ.get("DATABASE_URL", "").strip()
            if not database_url:
                raise ValueError("DATABASE_URL is required unless --jsonl is explicit")
            import psycopg

            database = load_database_module()
            with psycopg.connect(database_url) as connection:
                profile_snapshot = database.load_or_seed_profile(
                    connection, args.profile, args.config
                )
                annotation_profile = database.annotation_profile(profile_snapshot)

            def write_posting_batch(postings, observed_at):
                with psycopg.connect(database_url) as write_connection:
                    return database.persist_postings_with_disposition(
                        write_connection, postings, observed_at
                    )

            posting_writer = write_posting_batch

        result = _run_main_pipeline(
            args,
            date_string,
            harvested_at,
            enabled_sources,
            annotation_profile,
            profile_snapshot,
            posting_writer,
            unavailable_annotator,
        )
    except Exception as error:
        LOGGER.error("Job-feed configuration/output failure: %s", error)
        return 1

    print(json.dumps(result, sort_keys=True))
    return 0


def _run_main_pipeline(
    args: argparse.Namespace,
    date_string: str,
    harvested_at: str,
    enabled_sources: set[str],
    annotation_profile: dict[str, object] | None,
    profile_snapshot: dict[str, object] | None,
    posting_writer: Callable[[list[dict[str, object]], str], object] | None,
    unavailable_annotator: Callable[[dict[str, object]], None],
) -> dict[str, object]:
    if args.no_annotate:
        annotator = None
    else:
        try:
            annotator = load_luna_annotator(annotation_profile)
        except Exception as error:
            LOGGER.warning("Luna annotator unavailable at startup: %s", error)
            annotator = unavailable_annotator
    return run_pipeline(
        config_path=args.config,
        profile_path=args.profile,
        output_dir=args.output_dir,
        date_string=date_string,
        harvested_at=harvested_at,
        max_pages=args.max_pages,
        fetcher=fetch_html,
        before_request=RequestPacer(),
        recency_override=args.recency,
        annotator=annotator,
        enabled_sources=enabled_sources,
        jd_fetcher=load_full_jd_fetcher(),
        jd_fetch_cap=args.jd_fetch_cap,
        liveness_checker=load_liveness_checker(),
        profile_snapshot=profile_snapshot,
        posting_writer=posting_writer,
    )


if __name__ == "__main__":
    sys.exit(main())
