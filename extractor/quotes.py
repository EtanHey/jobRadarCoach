"""Exact source-quote validation shared by extracted facts."""

from __future__ import annotations

import re
from typing import Literal

from scraper.brain_contract import BrainValidationError

ExtractionFailureCategory = Literal[
    "evidence_quote",
    "location_context",
    "remote_consistency",
    "stack_uniqueness",
]
ExtractionFailureField = Literal["location", "remote", "seniority", "salary", "stack"]
_FAILURE_CATEGORIES = frozenset(
    {"evidence_quote", "location_context", "remote_consistency", "stack_uniqueness"}
)
_FAILURE_FIELDS = frozenset({"location", "remote", "seniority", "salary", "stack"})


class ExtractionValidationError(BrainValidationError):
    """Evidence rejection carrying only bounded diagnostic metadata."""

    def __init__(
        self,
        message: str,
        *,
        category: ExtractionFailureCategory,
        field: ExtractionFailureField,
    ) -> None:
        if category not in _FAILURE_CATEGORIES or field not in _FAILURE_FIELDS:
            raise ValueError("invalid extraction failure metadata")
        super().__init__(message)
        self.category = category
        self.field = field


def validate_quote(
    field: ExtractionFailureField,
    value: object,
    quote: object,
    raw_jd: str,
) -> None:
    if value is None:
        if quote is not None:
            raise ExtractionValidationError(
                f"unknown {field} cannot cite evidence",
                category="evidence_quote",
                field=field,
            )
        return
    if not isinstance(quote, str) or not quote.strip() or quote not in raw_jd:
        raise ExtractionValidationError(
            f"{field} evidence must be an exact nonblank quote",
            category="evidence_quote",
            field=field,
        )
    if isinstance(value, str) and (
        not value.strip() or not re.search(
            rf"(?<!\w){re.escape(value)}(?!\w)", quote, re.IGNORECASE
        )
    ):
        raise ExtractionValidationError(
            f"{field} value must occur in its evidence quote",
            category="evidence_quote",
            field=field,
        )
