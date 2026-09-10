"""Provider schemas for the structured interpretation and claim-audit calls."""
from typing import Literal

from pydantic import BaseModel, ConfigDict


class StrictResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ExtractedClaim(StrictResponse):
    field: Literal["company", "title", "location", "score", "apply_url"]
    value: str


class HiringEvidence(StrictResponse):
    field: Literal["reasons", "outcome"]
    quote: str


class HiringAssertion(StrictResponse):
    asserted: bool
    evidence: HiringEvidence | None


class AuditResponse(StrictResponse):
    claims: list[ExtractedClaim]
    stance: Literal["recommend", "weak_option", "poor_fit", "neutral"]
    unsupported: list[str]
    hiring_assertion: HiringAssertion


class NaturalSpeech(StrictResponse):
    sentence: str
    stance: Literal["recommend", "weak_option", "poor_fit", "neutral"]
