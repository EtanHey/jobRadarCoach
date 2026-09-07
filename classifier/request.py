"""Build and normalize a constrained Luna scoring wire contract."""

from __future__ import annotations

import copy
import json

from scraper.annotate import (
    FACTOR_BASES,
    LUNA_SCHEMA,
    PROFILE_EVIDENCE_IDS,
    REASON_FACTORS,
    WITHHELD_ABSTENTION_DETAIL,
    WITHHELD_PROFILE_EVIDENCE_IDS,
    _build_prompt,
)
from scraper.brain import BrainRequest


REASON_FIELDS = ["factor", "basis", "assessment", "evidence_ids", "detail"]


def _ordered_ids(posting_id: str, candidate_ids: set[str]) -> list[str]:
    return [posting_id, *sorted(candidate_ids)]


def _reason_schema(
    factor: str,
    basis: str,
    evidence_ids: list[str],
    *,
    assessment: str | None = None,
    detail: str | None = None,
) -> dict[str, object]:
    assessment_schema: dict[str, object] = {
        "type": "string",
        "enum": ["positive", "mixed", "negative", "unknown"],
    }
    detail_schema: dict[str, object] = {
        "type": "string",
        "minLength": 1,
        "maxLength": 200,
    }
    if assessment is not None:
        assessment_schema["enum"] = [assessment]
    if detail is not None:
        detail_schema["enum"] = [detail]
    minimum = 1 if basis == "posting" else 2
    return {
        "type": "object",
        "additionalProperties": False,
        "required": REASON_FIELDS,
        "properties": {
            "factor": {"type": "string", "enum": [factor]},
            "basis": {"type": "string", "enum": [basis]},
            "assessment": assessment_schema,
            "evidence_ids": {
                "type": "array",
                "minItems": minimum,
                "maxItems": len(evidence_ids),
                "items": {"type": "string", "enum": evidence_ids},
            },
            "detail": detail_schema,
        },
    }


def output_schema(
    posting_evidence_id: str,
    professional_evidence_ids: set[str],
) -> dict[str, object]:
    normal_ids = _ordered_ids(posting_evidence_id, professional_evidence_ids)
    preference_ids = _ordered_ids(
        posting_evidence_id, set(WITHHELD_PROFILE_EVIDENCE_IDS)
    )
    properties = copy.deepcopy(LUNA_SCHEMA["properties"])
    properties["reasons"] = {
        "type": "object",
        "additionalProperties": False,
        "required": REASON_FACTORS,
        "properties": {
            factor: _reason_schema(
                factor,
                FACTOR_BASES[factor],
                [posting_evidence_id] if factor == "employer_type" else (
                    preference_ids if factor == "preferences" else normal_ids
                ),
                assessment="unknown" if factor == "preferences" else None,
                detail=(
                    WITHHELD_ABSTENTION_DETAIL
                    if factor == "preferences"
                    else None
                ),
            )
            for factor in REASON_FACTORS
        },
    }
    properties["fit_line_evidence_ids"] = {
        "type": "array",
        "minItems": 2,
        "maxItems": len(normal_ids),
        "items": {"type": "string", "enum": normal_ids},
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "required": sorted(properties),
        "properties": properties,
    }


def build_request(
    posting: dict[str, object],
    profile: dict[str, object],
    history: list[dict[str, object]],
) -> BrainRequest:
    history = [
        {key: row[key] for key in (
            "evidence_id", "company", "role", "application_date", "outcome"
        ) if key in row}
        for row in history
    ]
    posting_evidence_id = f"posting:{posting['id']}"
    history_ids = [str(row["evidence_id"]) for row in history]
    professional_ids = (
        set(PROFILE_EVIDENCE_IDS) - set(WITHHELD_PROFILE_EVIDENCE_IDS)
    ) | {str(signal["evidence_id"]) for signal in profile["fit_signals"]} | set(
        history_ids
    )
    schema = output_schema(posting_evidence_id, professional_ids)
    prompt = "\n".join(
        [
            _build_prompt(posting, profile),
            "Wire format: reasons is a closed object keyed by the five exact factor names, not an array.",
            "Each keyed reason must repeat its schema-constrained factor and basis. All five keys are required exactly once.",
            "Copy every evidence ID byte-for-byte from its slot-specific schema enum. Never invent, alias, normalize, or add or remove an evidence-ID prefix.",
            "The preferences key is the only withheld-evidence slot; its assessment and detail are fixed by the schema.",
            "The local adapter copies the five keyed reasons into canonical order, then applies the unchanged semantic validator.",
            "Professional depth modes describe exposure, not advanced proficiency. Do not invent a calendar cutoff between hands-on and AI-directed work.",
            "Application history is professional context only: a previous company is never a hard block, and no cooldown may be invented.",
            "Unknown history fields remain unknown. Use only the explicitly projected fields below.",
            "Additional allowed application-history evidence IDs:",
            json.dumps(history_ids, ensure_ascii=False),
            "Bounded professional application history:",
            json.dumps(history, ensure_ascii=False, sort_keys=True),
        ]
    )
    return BrainRequest(prompt, schema)


def normalize_response(data: dict[str, object]) -> dict[str, object]:
    reasons = data.get("reasons")
    if not isinstance(reasons, dict) or set(reasons) != set(REASON_FACTORS):
        raise ValueError("wire reasons do not contain the exact factor keys")
    normalized_reasons: list[dict[str, object]] = []
    for factor in REASON_FACTORS:
        reason = reasons.get(factor)
        if (
            not isinstance(reason, dict)
            or reason.get("factor") != factor
            or reason.get("basis") != FACTOR_BASES[factor]
        ):
            raise ValueError("wire reason does not match its keyed contract")
        normalized_reasons.append(dict(reason))
    normalized = {key: value for key, value in data.items() if key != "reasons"}
    normalized["reasons"] = normalized_reasons
    return normalized
