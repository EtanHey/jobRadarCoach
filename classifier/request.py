"""Build and normalize a constrained Luna scoring wire contract."""

from __future__ import annotations

import copy
import json

from scraper.annotate import (
    FACTOR_BASES,
    LUNA_SCHEMA,
    MCP_EVIDENCE_IDS,
    MODEL_FIELDS,
    PROFILE_EVIDENCE_IDS,
    REASON_FACTORS,
    WITHHELD_ABSTENTION_DETAIL,
    WITHHELD_PROFILE_EVIDENCE_IDS,
    _build_prompt,
)
from scraper.brain import BrainRequest


REASON_FIELDS = ["factor", "basis", "assessment", "evidence_ids", "detail"]
DERIVED_FIELDS = {"fit_tier", "recommendation"}
WIRE_MODEL_FIELDS = MODEL_FIELDS - DERIVED_FIELDS
PROMPT_REPLACEMENTS = {
    "An explicit human verdict is authoritative: your recommendation must match it and may not override it.":
        "An explicit human recommendation is authoritative and is applied locally after model output; do not return or override it.",
    'If fit_tier is weak, fit_line MUST begin exactly "Weak fit —". Weak answers are expected; do not flatter.':
        'If fit_score is below 40, fit_line MUST begin exactly "Weak fit —". Low scores are expected; do not flatter.',
    "Return exactly five reasons, one for each named factor. Every reason must cite only allowed evidence IDs and must include the posting evidence ID.":
        "Return exactly five reasons, one for each named factor. Evidence fields follow the wire rules below.",
    "A posting-basis reason may describe only the posting and must cite only the posting evidence ID.":
        "A posting-basis reason may describe only the posting; its evidence is inserted locally and must not be returned.",
    "A comparison-basis reason must cite at least one candidate profile evidence ID as well as the posting evidence ID.":
        "A comparison-basis reason must cite exactly one candidate evidence ID; posting evidence is inserted locally and must not be returned.",
    "Fit-line evidence IDs must include the posting ID and at least one candidate evidence ID; cite only evidence that supports the fit line.":
        "Fit-line evidence IDs must contain exactly one candidate evidence ID; posting evidence is inserted locally and must not be returned.",
}


def _reason_schema(
    factor: str,
    basis: str,
    candidate_evidence_ids: list[str] | None,
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
    required = [field for field in REASON_FIELDS if (
        field != "evidence_ids" or candidate_evidence_ids is not None
    )]
    properties: dict[str, object] = {
        "factor": {"type": "string", "enum": [factor]},
        "basis": {"type": "string", "enum": [basis]},
        "assessment": assessment_schema,
        "detail": detail_schema,
    }
    if candidate_evidence_ids is not None:
        properties["evidence_ids"] = {
            "type": "array",
            "minItems": 1,
            "maxItems": 1,
            "items": {"type": "string", "enum": candidate_evidence_ids},
        }
    return {
        "type": "object",
        "additionalProperties": False,
        "required": required,
        "properties": properties,
    }


def output_schema(
    posting_evidence_id: str,
    professional_evidence_ids: set[str],
) -> dict[str, object]:
    normal_ids = sorted(professional_evidence_ids)
    preference_ids = sorted(WITHHELD_PROFILE_EVIDENCE_IDS)
    properties = copy.deepcopy(LUNA_SCHEMA["properties"])
    for field in DERIVED_FIELDS:
        properties.pop(field)
    properties["reasons"] = {
        "type": "object",
        "additionalProperties": False,
        "required": REASON_FACTORS,
        "properties": {
            factor: _reason_schema(
                factor,
                FACTOR_BASES[factor],
                None if factor == "employer_type" else (
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
        "minItems": 1,
        "maxItems": 1,
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
    base_prompt = _build_prompt(posting, profile)
    for canonical, wire in PROMPT_REPLACEMENTS.items():
        if canonical not in base_prompt:
            raise ValueError("canonical scoring prompt changed")
        base_prompt = base_prompt.replace(canonical, wire)
    slot_ids = {
        factor: (
            [] if factor == "employer_type"
            else sorted(WITHHELD_PROFILE_EVIDENCE_IDS)
            if factor == "preferences"
            else sorted(professional_ids)
        )
        for factor in REASON_FACTORS
    }
    slot_ids["fit_line"] = sorted(professional_ids)
    mcp_ids = sorted(professional_ids & MCP_EVIDENCE_IDS)
    prompt = "\n".join(
        [
            base_prompt,
            "Wire format: reasons is a closed object keyed by the five exact factor names, not an array.",
            "Each keyed reason must repeat its schema-constrained factor and basis. All five keys are required exactly once.",
            "Copy every evidence ID byte-for-byte from its slot-specific schema enum. Never invent, alias, normalize, or add or remove an evidence-ID prefix.",
            "Return exactly one candidate evidence ID for each comparison reason and fit line. Return no evidence_ids field for employer_type. The local adapter inserts the current posting ID exactly once.",
            "Make each comparison detail and fit line one source-scoped claim. Do not combine evidence from multiple projects in one claim.",
            "For an MCP claim, select exactly one allowed MCP evidence ID; if none is allowed, do not make an MCP claim.",
            "Allowed MCP evidence IDs for this request:",
            json.dumps(mcp_ids, ensure_ascii=False),
            "Full slot-specific allowed candidate evidence ID enums:",
            json.dumps(slot_ids, ensure_ascii=False, sort_keys=True),
            "The preferences key is the only withheld-evidence slot; its assessment and detail are fixed by the schema.",
            "The local adapter copies the five keyed reasons into canonical order, then applies the unchanged semantic validator.",
            "Do not return fit_tier or recommendation. The local adapter derives fit_tier from fit_score using strong=80-100, good=60-79, stretch=40-59, weak=0-39.",
            "Local score policy: 60-100=apply, 40-59=review, 0-39=skip. Referral is never inferred from score; an explicit authoritative human recommendation is preserved locally.",
            "Professional depth modes describe exposure, not advanced proficiency. Do not invent a calendar cutoff between hands-on and AI-directed work.",
            "For each reason and fit line, cite the smallest set of evidence IDs that directly supports that text; never attach unrelated project IDs.",
            "For employer_type, describe only whether the named employer is hiring directly or through an agency; do not repeat the posting's specialty or title.",
            'For non-preferences comparison reasons and fit_line, cite concrete verified candidate work and refer to posting specialty labels only as "this role", including in negative comparisons.',
            "For every cited ID, omit its evidence_scoped_prohibitions phrases entirely, including negations, quotations, and missing-experience statements. Use supported neutral wording for limitations; never evade a prohibition by inventing a skill.",
            "Application history is professional context only: a previous company is never a hard block, and no cooldown may be invented.",
            "Unknown history fields remain unknown. Use only the explicitly projected fields below.",
            "Additional allowed application-history evidence IDs:",
            json.dumps(history_ids, ensure_ascii=False),
            "Bounded professional application history:",
            json.dumps(history, ensure_ascii=False, sort_keys=True),
        ]
    )
    return BrainRequest(prompt, schema)


def normalize_response(
    data: dict[str, object], *, posting_evidence_id: str,
    expected_recommendation: str | None,
) -> dict[str, object]:
    if set(data) != WIRE_MODEL_FIELDS:
        raise ValueError("wire response does not contain the exact model fields")
    fit_score = data.get("fit_score")
    if type(fit_score) is not int or not 0 <= fit_score <= 100:
        raise ValueError("fit score must be an integer between 0 and 100")
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
        normalized_reason = dict(reason)
        if factor == "employer_type":
            if "evidence_ids" in normalized_reason:
                raise ValueError("posting-only wire reason supplied evidence IDs")
            normalized_reason["evidence_ids"] = [posting_evidence_id]
        else:
            candidate_ids = normalized_reason.get("evidence_ids")
            if (
                not isinstance(candidate_ids, list)
                or len(candidate_ids) != 1
                or not isinstance(candidate_ids[0], str)
                or not candidate_ids[0]
                or candidate_ids[0] == posting_evidence_id
            ):
                raise ValueError("comparison wire reason must cite one candidate ID")
            normalized_reason["evidence_ids"] = [
                posting_evidence_id, candidate_ids[0],
            ]
        normalized_reasons.append(normalized_reason)
    fit_line_ids = data.get("fit_line_evidence_ids")
    if (
        not isinstance(fit_line_ids, list)
        or len(fit_line_ids) != 1
        or not isinstance(fit_line_ids[0], str)
        or not fit_line_ids[0]
        or fit_line_ids[0] == posting_evidence_id
    ):
        raise ValueError("fit line must cite one candidate ID")
    normalized = {key: value for key, value in data.items() if key != "reasons"}
    normalized["reasons"] = normalized_reasons
    normalized["fit_line_evidence_ids"] = [posting_evidence_id, fit_line_ids[0]]
    normalized["fit_tier"] = (
        "strong" if fit_score >= 80 else "good" if fit_score >= 60
        else "stretch" if fit_score >= 40 else "weak"
    )
    normalized["recommendation"] = expected_recommendation or (
        "apply" if fit_score >= 60 else "review" if fit_score >= 40 else "skip"
    )
    return normalized
