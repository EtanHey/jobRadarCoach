"""Pure Luna scoring core over one captured database snapshot."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Iterator, Literal

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
from scraper.brain import BrainRequest, BrainResponseError, BrainResult, run_brain


MAX_ATTEMPTS = 2

BrainRunner = Callable[[BrainRequest, Mapping[str, object]], BrainResult]
DiagnosticCategory = Literal["projection", "provider", "wire", "semantic"]
DiagnosticCallback = Callable[[DiagnosticCategory], None]
_DIAGNOSTIC_CALLBACK: ContextVar[DiagnosticCallback | None] = ContextVar(
    "classifier_diagnostic_callback", default=None
)


@contextmanager
def diagnostic_scope(callback: DiagnosticCallback) -> Iterator[None]:
    """Make a sanitized diagnostic callback visible through persistence."""

    token = _DIAGNOSTIC_CALLBACK.set(callback)
    try:
        yield
    finally:
        _DIAGNOSTIC_CALLBACK.reset(token)


def _diagnose(callback: DiagnosticCallback | None, category: DiagnosticCategory) -> None:
    if callback is None:
        return
    try:
        callback(category)
    except Exception:
        pass

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
    diagnostic: DiagnosticCallback | None = None,
) -> ScoringResult | None:
    """Return validated annotation and provenance, or ``None`` on any failure."""

    if diagnostic is None:
        diagnostic = _DIAGNOSTIC_CALLBACK.get()
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
        _diagnose(diagnostic, "projection")
        return None

    attempted_brain: str | None = None
    for _attempt in range(MAX_ATTEMPTS):
        try:
            result = brain_runner(request, profile_snapshot)
        except BrainResponseError:
            _diagnose(diagnostic, "wire")
            return None
        except Exception:
            _diagnose(diagnostic, "provider")
            return None
        if not isinstance(result, BrainResult):
            _diagnose(diagnostic, "wire")
            return None
        if attempted_brain is not None and result.brain != attempted_brain:
            _diagnose(diagnostic, "provider")
            return None
        attempted_brain = result.brain
        try:
            normalized = normalize_response(
                result.data,
                posting_evidence_id=posting_evidence_id,
                expected_recommendation=expected,
            )
        except Exception:
            _diagnose(diagnostic, "wire")
            return None
        try:
            annotation = _validated_annotation(
                normalized,
                profile=profile,
                allowed_evidence_ids=allowed_evidence_ids,
                posting_evidence_id=posting_evidence_id,
                expected_recommendation=expected,
            )
        except Exception:
            _diagnose(diagnostic, "semantic")
            return None
        if annotation is not None:
            return ScoringResult(annotation, result.brain, result.model)
    _diagnose(diagnostic, "semantic")
    return None
