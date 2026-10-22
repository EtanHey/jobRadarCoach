"""Explicit posting-title levels shared by extraction and classification."""

from __future__ import annotations

from dataclasses import dataclass
import re


_TITLE_LEVEL = re.compile(
    r"(?<!\w)(?:(?ai:senior|sr\.?|lead|staff|principal|junior)|בכיר|ג['׳’]וניור)(?!\w)",
)
_LEVELS = {
    "senior": "senior", "sr": "senior", "בכיר": "senior",
    "lead": "lead_manager", "staff": "staff_principal", "principal": "staff_principal",
    "junior": "junior", "ג'וניור": "junior",
}
_MANAGER = re.compile(r"(?<!\w)(?ai:manager)(?!\w)")
_MANAGEMENT_HEAD = re.compile(
    r"(?<!\w)(?:(?ai:head(?=\s+of\b)|director|vp)|ראש\s+צוות|מנהל\s+פיתוח)(?!\w)",
)
_PEOPLE_ORG = re.compile(
    r"(?<!\w)(?ai:engineering|software|r&d|development|developer|team|group)(?!\w)",
)
_FUNCTION_HEAD = re.compile(
    r"(?<!\w)(?ai:program|product|project|account|marketing|partner|customer\s+success|delivery)\s*$",
)


def _management_head(title: str) -> str | None:
    if head := _MANAGEMENT_HEAD.search(title):
        return head[0]
    for manager in _MANAGER.finditer(title):
        modifier = title[:manager.start()]
        grades = list(_TITLE_LEVEL.finditer(modifier))
        if grades:
            modifier = modifier[grades[-1].end():]
        # Inverted titles put the organization after an otherwise bare Manager.
        if not modifier.strip() and title[manager.end():].lstrip().startswith(","):
            modifier = title[manager.end():].lstrip()[1:]
        modifier = re.split(r"[,;()/]|\s[-–—]\s", modifier)[0].strip()
        # A functional head owns its preceding domain: Engineering Program
        # Manager is program management, even though Engineering appears earlier.
        if not _FUNCTION_HEAD.search(modifier) and _PEOPLE_ORG.search(modifier):
            return manager[0]
    return None


@dataclass(frozen=True)
class TitleSeniority:
    level: str | None
    value: str | None
    evidence_quote: str | None
    remark: str | None = None

    def fact(self) -> dict[str, str | None]:
        return {"value": self.value, "evidence_quote": self.evidence_quote}


def title_seniority(title: object) -> TitleSeniority | None:
    """Return a quoted title grade, or an explicit abstention for ambiguous roles."""
    if not isinstance(title, str):
        return None
    matches = list(_TITLE_LEVEL.finditer(title))
    levels = {
        _LEVELS[match[0].casefold().rstrip(".").replace("׳", "'").replace("’", "'")]
        for match in matches
    }
    if len(levels) > 1:
        return TitleSeniority(None, None, None, title[:1000])
    if head := _management_head(title):
        level, value = "lead_manager", head
    elif matches:
        level, value = levels.pop(), matches[0][0]
    elif _MANAGER.search(title):
        # Prevent extracted/ATS fallback from promoting an ungraded function.
        return TitleSeniority(None, None, None, title[:1000])
    else:
        return None
    return TitleSeniority(level, value, title if len(title) <= 1000 else value)


def apply_title_seniority(facts: dict[str, object], title: object) -> TitleSeniority | None:
    explicit = title_seniority(title)
    if explicit is not None:
        facts["seniority"] = explicit.fact()
        facts.pop("seniority_remark", None)
        if explicit.remark is not None:
            facts["seniority_remark"] = explicit.remark
    return explicit
