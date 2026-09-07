"""Pure Luna scoring core over one captured database snapshot."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from classifier.projection import (
    history_projection as _history_projection,
    profile_contract as _profile_contract,
    public_posting as _public_posting,
)
from classifier.request import (
    build_request as _request,
    normalize_response,
)

from scraper.annotate import (
    PROFILE_EVIDENCE_IDS,
    _expected_human_recommendation,
    _validated_annotation,
)
from scraper.brain import BrainRequest, BrainResult, run_brain


MAX_ATTEMPTS = 2

BrainRunner = Callable[[BrainRequest, Mapping[str, object]], BrainResult]

@dataclass(frozen=True)
class ScoringResult:
    annotation: dict[str, object]
    brain: str
    model: str

def score_posting(
    profile_snapshot: Mapping[str, object],
    posting: Mapping[str, object],
    application_history: Sequence[Mapping[str, object]],
    *,
    brain_runner: BrainRunner = run_brain,
) -> ScoringResult | None:
    """Return validated annotation and provenance, or ``None`` on any failure."""

    try:
        profile = _profile_contract(profile_snapshot)
        luna_posting = _public_posting(posting)
        history = _history_projection(application_history)
        request = _request(luna_posting, profile, history)
        posting_evidence_id = f"posting:{luna_posting['id']}"
        allowed_evidence_ids = (
            {posting_evidence_id}
            | PROFILE_EVIDENCE_IDS
            | {str(signal["evidence_id"]) for signal in profile["fit_signals"]}
            | {str(row["evidence_id"]) for row in history}
        )
        expected = _expected_human_recommendation(luna_posting)
    except Exception:
        return None

    attempted_brain: str | None = None
    for _attempt in range(MAX_ATTEMPTS):
        try:
            result = brain_runner(request, profile_snapshot)
            if not isinstance(result, BrainResult):
                return None
            if attempted_brain is not None and result.brain != attempted_brain:
                return None
            attempted_brain = result.brain
            annotation = _validated_annotation(
                normalize_response(result.data),
                profile=profile,
                allowed_evidence_ids=allowed_evidence_ids,
                posting_evidence_id=posting_evidence_id,
                expected_recommendation=expected,
            )
        except Exception:
            return None
        if annotation is not None:
            return ScoringResult(annotation, result.brain, result.model)
    return None
