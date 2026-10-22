"""Conservative, I/O-free comparisons of explicitly scoped duration evidence."""

from __future__ import annotations

import re
from collections.abc import Mapping


_YEARS = re.compile(
    r"(?<![\w.\-–])(?P<years>\d+(?:\.\d+)?)"
    r"(?:\s*[-–]\s*(?P<upper>\d+(?:\.\d+)?))?\s*(?P<plus>\+)?\s*"
    r"(?:years?|yrs?)\b[’']?\s*(?P<tail>[^\n;]*?)(?=\.(?:\s|$)|[\n;]|$)",
    re.I,
)
# Closed duration-subject vocabulary for the supported skill frames. A role,
# arbitrary sentence tail, or composite subject is not specialist evidence.
_SPECIALIST_SUBJECTS = frozenset({"react", "angular", "llm-based ai solutions", "backend"})
_OVERALL = re.compile(r"(?:professional )?software (?:development|engineering)")
_REQUIREMENT_PREFIX = re.compile(
    r"\s*[-*•]*\s*(?:requirements?\s*:\s*)?"
    r"(?:(?:you (?:must )?have|must have|requires?|minimum(?: of)?|at least)\s+)?",
    re.I,
)
_SECTION_HEADING = re.compile(
    r"^[ \t]*(?:#{1,6}[ \t]+)?(?:\*\*|__)?([^\W\d_][^\n]*?):?"
    r"(?:\*\*|__)?[ \t]*:?[ \t]*$", re.M,
)
_REQUIRED_SECTION = re.compile(
    r"(?:(?:minimum|required|mandatory) )?(?:requirements?|qualifications?|skills)|required|mandatory|must have",
    re.I,
)
_MANDATORY_SUFFIX = re.compile(r"\s+(?:[-–—]\s*(?:mandatory|required)|\((?:mandatory|required)\))\s*$", re.I)


def _required_section(prefix: str) -> bool:
    # Only complete preceding lines set section scope. Unknown headings default
    # to non-mandatory; a subsequent requirements heading restores that scope.
    complete_lines = prefix.rpartition("\n")[0]
    # Detect boundaries independently of language/punctuation, then classify
    # the title. Duration clauses themselves must not end the current section.
    headings = [heading for heading in _SECTION_HEADING.finditer(complete_lines)
                if _YEARS.search(heading[1]) is None]
    return not headings or _REQUIRED_SECTION.fullmatch(headings[-1][1].strip()) is not None


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
    return text, "specialist" if text in _SPECIALIST_SUBJECTS else "unknown"


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
        if not _required_section(jd[:match.start()]):
            continue
        prefix = re.split(r"\n|;|\.(?:\s|$)", jd[:match.start()])[-1]
        if _REQUIREMENT_PREFIX.fullmatch(prefix) is None:
            continue
        # Keep qualifiers in the quote. Only an explicit mandatory suffix may
        # be removed for subject matching; every other qualifier defaults out.
        subject, kind = _subject(_MANDATORY_SUFFIX.sub("", match["tail"]))
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
