"""Conservative, I/O-free comparisons of explicitly scoped duration evidence."""

from __future__ import annotations

import re
from collections.abc import Mapping


_YEARS = re.compile(
    r"(?<![\w.\-–])(?P<years>\d+(?:\.\d+)?)"
    r"(?:\s*[-–]\s*(?P<upper>\d+(?:\.\d+)?))?\s*(?P<plus>\+)?\s*"
    r"(?:years?|yrs?)\b[’']?\s*(?P<tail>[^\n;–—]*?)(?=\.(?:\s|$)|[\n;–—]|$)",
    re.I,
)
_OVERALL = re.compile(r"(?:professional )?software (?:development|engineering)")
_REQUIREMENT_PREFIX = re.compile(
    r"\s*[-*•]*\s*(?:requirements?\s*:\s*)?"
    r"(?:(?:you (?:must )?have|must have|requires?|minimum(?: of)?|at least)\s+)?",
    re.I,
)


def _subject(tail: str) -> tuple[str, str]:
    text = " ".join(tail.casefold().strip(" .,:*").split())
    text = re.sub(r"^(?:of\s+)?(?:hands-on\s+)?(?:experience\s*)?", "", text)
    text = re.sub(r"^(?:in|with|developing|using)\s+", "", text)
    text = re.sub(r"\s+experience$", "", text)
    if _OVERALL.fullmatch(text):
        return "overall", "overall"
    text = re.sub(r"\s+development$", "", text)
    if not text or text == "experience":
        return "unknown", "unknown"
    return text, "specialist"


def compare_experience(jd: str, profile: Mapping[str, object]) -> list[dict[str, object]]:
    """Never infer skill duration from tags, depth modes, dates or overall tenure.

    Only a complete verified claim in the duration-first grammar establishes a
    candidate duration. Exact normalized subjects match; projects never sum.
    Unparsed subject wording deliberately stays unknown rather than using tenure.
    """
    evidence: dict[str, tuple[float, list[str], bool]] = {}
    for signal in profile["fit_signals"]:
        if signal.get("status") != "verified":
            continue
        match = _YEARS.fullmatch(signal["claim"].strip().rstrip("."))
        if match is None:
            continue
        subject, kind = _subject(match["tail"])
        years = float(match["years"])
        if kind != "specialist" or not 0 <= years <= 100:
            continue
        previous = evidence.get(subject)
        if previous is None or years > previous[0]:
            evidence[subject] = years, [signal["evidence_id"]], bool(match["plus"] or match["upper"])

    comparisons = []
    for match in _YEARS.finditer(jd):
        prefix = re.split(r"\n|;|\.(?:\s|$)", jd[:match.start()])[-1]
        if _REQUIREMENT_PREFIX.fullmatch(prefix) is None:
            continue
        subject, kind = _subject(match["tail"])
        required = float(match["years"])
        candidate_years, ids, lower_bound = (
            (profile["candidate"]["tenure_years"], ["profile:tenure"], False)
            if kind == "overall" else evidence.get(subject, (None, [], False))
        )
        assessment = "unknown" if candidate_years is None else (
            "met" if candidate_years >= required else "unknown" if lower_bound else "below"
        )
        comparisons.append({
            "requirement_quote": match[0], "subject": subject, "subject_kind": kind,
            "required_years": required, "candidate_years": candidate_years,
            "candidate_years_is_minimum": lower_bound,
            "candidate_evidence_ids": ids,
            "assessment": assessment,
            "remark": "Duration is not established for this exact subject."
            if assessment == "unknown" else "Only matching duration evidence is compared.",
        })
    return comparisons
