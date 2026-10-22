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
_MANAGEMENT_HEAD = re.compile(r"\b(?:manager|head|director)\b", re.IGNORECASE | re.ASCII)


@dataclass(frozen=True)
class TitleSeniority:
    level: str | None
    value: str | None
    evidence_quote: str | None
    remark: str | None = None

    def fact(self) -> dict[str, str | None]:
        return {"value": self.value, "evidence_quote": self.evidence_quote}


def title_seniority(title: object) -> TitleSeniority | None:
    """Return a quoted level, or unknown for conflicting explicit title levels."""
    if not isinstance(title, str):
        return None
    matches = list(_TITLE_LEVEL.finditer(title))
    if not matches:
        return None
    levels = {
        _LEVELS[match[0].casefold().rstrip(".").replace("׳", "'").replace("’", "'")]
        for match in matches
    }
    if len(levels) != 1:
        return TitleSeniority(None, None, None, title[:1000])
    level = levels.pop()
    if level == "senior" and _MANAGEMENT_HEAD.search(title):
        # Senior modifies the management role; retain the existing management bucket.
        level = "lead_manager"
    value = matches[0][0]
    return TitleSeniority(level, value, title if len(title) <= 1000 else value)


def apply_title_seniority(facts: dict[str, object], title: object) -> TitleSeniority | None:
    explicit = title_seniority(title)
    if explicit is not None:
        facts["seniority"] = explicit.fact()
        facts.pop("seniority_remark", None)
        if explicit.remark is not None:
            facts["seniority_remark"] = explicit.remark
    return explicit
