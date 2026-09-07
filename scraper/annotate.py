#!/usr/bin/env python3
"""Fail-closed Luna annotations for one harvested job posting."""

from __future__ import annotations

import copy
from datetime import datetime
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from itertools import combinations
from typing import Callable


LOGGER = logging.getLogger("coach.jobfeed.luna")
SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
DEFAULT_PROFILE_PATH = REPO_ROOT / "profile.yaml"
LUNA_REASONING_EFFORT = "xhigh"
REASON_FACTORS = [
    "product_role_match",
    "stack_domain_evidence",
    "seniority_gap",
    "employer_type",
    "preferences",
]
MODEL_FIELDS = {
    "employer_type",
    "seniority_real",
    "fit_score",
    "fit_tier",
    "recommendation",
    "reasons",
    "fit_line",
    "fit_line_evidence_ids",
}
LUNA_SCHEMA: dict[str, object] = {
    "type": "object",
    "additionalProperties": False,
    "required": sorted(MODEL_FIELDS),
    "properties": {
        "employer_type": {
            "type": "string",
            "enum": ["direct", "agency", "unknown"],
        },
        "seniority_real": {
            "type": ["boolean", "null"],
        },
        "fit_score": {"type": "integer", "minimum": 0, "maximum": 100},
        "fit_tier": {
            "type": "string",
            "enum": ["strong", "good", "stretch", "weak"],
        },
        "recommendation": {
            "type": "string",
            "enum": ["apply", "referral", "review", "skip"],
        },
        "reasons": {
            "type": "array",
            "minItems": 5,
            "maxItems": 5,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "factor",
                    "basis",
                    "assessment",
                    "evidence_ids",
                    "detail",
                ],
                "properties": {
                    "factor": {"type": "string", "enum": REASON_FACTORS},
                    "basis": {
                        "type": "string",
                        "enum": ["posting", "comparison"],
                    },
                    "assessment": {
                        "type": "string",
                        "enum": ["positive", "mixed", "negative", "unknown"],
                    },
                    "evidence_ids": {
                        "type": "array",
                        "minItems": 1,
                        "items": {"type": "string", "minLength": 1},
                    },
                    "detail": {"type": "string", "minLength": 1, "maxLength": 200},
                },
            },
        },
        "fit_line": {"type": "string", "maxLength": 160},
        "fit_line_evidence_ids": {
            "type": "array",
            "minItems": 2,
            "items": {"type": "string", "minLength": 1},
        },
    },
}
INVALID_ANNOTATION: dict[str, object] = {
    "employer_type": "unknown",
    "seniority_real": None,
    "fit_score": 0,
    "fit_tier": "weak",
    "recommendation": "review",
    "reasons": [],
    "fit_line": "",
    "fit_line_evidence_ids": [],
    "luna_status": "invalid",
}

FIT_TIER_RANGES = {
    "strong": range(80, 101),
    "good": range(60, 80),
    "stretch": range(40, 60),
    "weak": range(0, 40),
}
RECOMMENDATIONS = {"apply", "referral", "review", "skip"}
MCP_EVIDENCE_IDS = {"brainlayer", "voicelayer", "cmuxlayer"}
PROFILE_EVIDENCE_IDS = {
    "profile:tenure",
    "profile:open-to",
    "profile:preferences",
}
HUMAN_RECOMMENDATIONS = {
    "apply": "apply",
    "applied": "apply",
    "referral": "referral",
    "interesting": "referral",
    "skip": "skip",
    "not_relevant": "skip",
}
FACTOR_BASES = {
    "product_role_match": "comparison",
    "stack_domain_evidence": "comparison",
    "seniority_gap": "comparison",
    "employer_type": "posting",
    "preferences": "comparison",
}

Runner = Callable[[str, dict[str, object]], object]


def _invalid_annotation() -> dict[str, object]:
    return copy.deepcopy(INVALID_ANNOTATION)


def _projection_strings(value: object):
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from _projection_strings(item)
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from _projection_strings(key)
            yield from _projection_strings(item)


def _contains_absolute_path(value: str) -> bool:
    return bool(
        re.search(r"\bfile://", value, re.I)
        or re.search(r"(?<![\w:/])/(?:[^\s/]+(?:/[^\s/]*)*|$)", value)
        or re.search(r"(?<![\w])[A-Za-z]:[\\/]", value)
        or re.search(r"(?<!\\)\\\\[^\\\s]+\\[^\\\s]+", value)
    )


# Existing validation flow is retained from source relocation; debt is tracked.
def _load_safe_profile_contract(path: Path) -> dict[str, object]:  # skipcq: PY-R1000
    """Load only the embedded JSON safe projection; legacy v1 fields stay private."""

    raw_text = path.read_text(encoding="utf-8")
    versions = re.findall(r"(?m)^contract_version:\s*(\d+)\s*$", raw_text)
    if versions != ["1"]:
        raise ValueError("profile contract_version must be exactly 1")
    marker = "safe_radar_projection:\n"
    if raw_text.count(marker) != 1:
        raise ValueError("safe_radar_projection must appear exactly once")
    block = raw_text.split(marker, 1)[1]
    block_lines = block.splitlines()
    if not block_lines or any(
        line and not line.startswith("  ") for line in block_lines
    ):
        raise ValueError("safe_radar_projection must be the final indented JSON block")
    try:
        projection = json.loads("\n".join(line[2:] for line in block_lines))
    except json.JSONDecodeError as error:
        raise ValueError("safe_radar_projection must contain valid JSON") from error

    def exact_mapping(value: object, keys: set[str], field: str) -> dict[str, object]:
        if not isinstance(value, dict) or set(value) != keys:
            raise ValueError(f"{field} must contain exactly {sorted(keys)}")
        return value

    def string(value: object, field: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field} must be a non-empty string")
        return value.strip()

    def string_list(
        value: object, field: str, *, allow_empty: bool = False
    ) -> list[str]:
        if not isinstance(value, list) or (not value and not allow_empty):
            raise ValueError(f"{field} must be a list")
        normalized = [string(item, field) for item in value]
        if len(normalized) != len(set(normalized)):
            raise ValueError(f"{field} must not contain duplicates")
        return normalized

    root = exact_mapping(
        projection,
        {"projection_version", "candidate", "fit_signals", "constraints"},
        "safe_radar_projection",
    )
    if root["projection_version"] != 1:
        raise ValueError("safe radar projection_version must be exactly 1")
    candidate = exact_mapping(
        root["candidate"],
        {
            "positioning",
            "tenure_years",
            "location",
            "fit_terms",
            "open_to",
            "preferences",
        },
        "candidate",
    )
    string(candidate["positioning"], "candidate.positioning")
    string(candidate["location"], "candidate.location")
    tenure = candidate["tenure_years"]
    if type(tenure) not in {int, float} or not 0 <= float(tenure) <= 100:
        raise ValueError("candidate.tenure_years must be a non-negative number")
    string_list(candidate["fit_terms"], "candidate.fit_terms")
    open_to = exact_mapping(
        candidate["open_to"],
        {"geographies", "work_modes", "relocation"},
        "candidate.open_to",
    )
    string_list(open_to["geographies"], "candidate.open_to.geographies")
    work_modes = string_list(open_to["work_modes"], "candidate.open_to.work_modes")
    if not set(work_modes) <= {"on-site", "hybrid", "remote"}:
        raise ValueError("candidate.open_to.work_modes contains an unknown mode")
    if type(open_to["relocation"]) is not bool:
        raise ValueError("candidate.open_to.relocation must be boolean")
    preferences = exact_mapping(
        candidate["preferences"],
        {"product_company", "experience_gap"},
        "candidate.preferences",
    )
    if preferences["product_company"] != "preferred":
        raise ValueError("candidate.preferences.product_company must be preferred")
    gap = exact_mapping(
        preferences["experience_gap"],
        {"max_years_below_requirement", "treatment"},
        "candidate.preferences.experience_gap",
    )
    max_gap = gap["max_years_below_requirement"]
    if type(max_gap) not in {int, float} or not 0 <= float(max_gap) <= 1:
        raise ValueError("experience gap must be between zero and one year")
    if gap["treatment"] != "weigh-not-wall":
        raise ValueError("experience gap treatment must be weigh-not-wall")

    signals = root["fit_signals"]
    if not isinstance(signals, list) or not signals:
        raise ValueError("fit_signals must be a non-empty list")
    seen_ids: set[str] = set()
    for index, signal_value in enumerate(signals):
        signal = exact_mapping(
            signal_value,
            {"evidence_id", "tags", "claim", "ownership", "status"},
            f"fit_signals[{index}]",
        )
        evidence_id = string(signal["evidence_id"], "fit signal evidence_id")
        if evidence_id in seen_ids:
            raise ValueError(f"duplicate fit signal evidence_id: {evidence_id}")
        if not re.fullmatch(r"[a-z0-9][a-z0-9:-]*", evidence_id):
            raise ValueError(f"malformed fit signal evidence_id: {evidence_id}")
        tags = string_list(signal["tags"], f"fit signal {evidence_id}.tags")
        string(signal["claim"], f"fit signal {evidence_id}.claim")
        ownership = exact_mapping(
            signal["ownership"],
            {"verified_scope", "exclusions"},
            f"fit signal {evidence_id}.ownership",
        )
        string(ownership["verified_scope"], "ownership.verified_scope")
        string_list(ownership["exclusions"], "ownership.exclusions")
        if signal["status"] != "verified":
            raise ValueError(f"fit signal {evidence_id} must be verified")
        if "mcp" in tags and evidence_id not in MCP_EVIDENCE_IDS:
            raise ValueError(f"fit signal {evidence_id} is not genuine MCP evidence")
        seen_ids.add(evidence_id)

    constraints = exact_mapping(
        root["constraints"],
        {"global_never_claims", "evidence_scoped_prohibitions"},
        "constraints",
    )
    string_list(constraints["global_never_claims"], "global_never_claims")
    scoped = constraints["evidence_scoped_prohibitions"]
    if not isinstance(scoped, dict):
        raise ValueError("evidence_scoped_prohibitions must be a mapping")
    for evidence_id, wording in scoped.items():
        string(evidence_id, "scoped evidence_id")
        string_list(wording, f"scoped prohibitions for {evidence_id}")
    if "voice-agent-tool-calling" in seen_ids and "MCP" not in scoped.get(
        "voice-agent-tool-calling", []
    ):
        raise ValueError("voice-agent-tool-calling must remain scoped as not MCP")

    if any(_contains_absolute_path(value) for value in _projection_strings(root)):
        raise ValueError("path-like value in safe_radar_projection")
    return root


def _expected_human_recommendation(posting: dict[str, object]) -> str | None:
    raw = posting.get("human_verdict", posting.get("verdict"))
    if not isinstance(raw, str):
        return None
    return HUMAN_RECOMMENDATIONS.get(raw.strip().lower())


def _build_prompt(posting: dict[str, object], profile: dict[str, object]) -> str:
    posting_id = str(posting.get("id", "")).strip()
    public_posting = {
        "id": posting_id,
        "title": str(posting.get("title", "")),
        "company": str(posting.get("company", "")),
        "location": str(posting.get("location", "")),
        "jd_text": str(posting.get("jd_text", "")),
    }
    human_recommendation = _expected_human_recommendation(posting)
    if human_recommendation is not None:
        public_posting["explicit_human_recommendation"] = human_recommendation
    allowed_evidence_ids = sorted(
        {f"posting:{posting_id}"}
        | PROFILE_EVIDENCE_IDS
        | {
            str(signal["evidence_id"])
            for signal in profile.get("fit_signals", [])
            if isinstance(signal, dict) and signal.get("evidence_id")
        }
    )
    return "\n".join(
        [
            "Annotate this public job posting for the private morning triage feed.",
            "Do not use tools or modify files; reason only from the supplied profile and posting.",
            "Return only the requested JSON fields. This is an advisory ranking, never a human verdict.",
            "Employer type: direct means the named company is hiring for itself; agency means a recruiter/staffing firm is posting for a client; otherwise unknown.",
            "Seniority real: true when the JD's actual scope or experience bar is genuinely senior, false when the title is inflated, null when unclear.",
            "Comparatively weigh product and role match, demonstrated stack and domain evidence, seniority gap, employer type, and preferences.",
            "Allowed geography must not reduce fit. Relocation and remote modes are explicit in the profile.",
            "A requirement gap of less than one year is evidence to weigh, not an automatic wall.",
            "Treat product-company preference as a preference, not a fabricated hard constraint.",
            "Fit tiers are exact: strong=80-100, good=60-79, stretch=40-59, weak=0-39.",
            "Recommendation semantics: apply=direct application now; referral=worth pursuing through a warm path; review=insufficient or conflicting evidence; skip=material mismatch outweighs positives.",
            "Return exactly five reasons, one for each named factor. Every reason must cite only allowed evidence IDs and must include the posting evidence ID.",
            "Reason basis is exact: employer_type uses posting; every other factor uses comparison.",
            "A posting-basis reason may describe only the posting and must cite only the posting evidence ID.",
            "A comparison-basis reason must cite at least one candidate profile evidence ID as well as the posting evidence ID.",
            "Use profile:tenure only for stated tenure, profile:open-to only for geography/modes, and profile:preferences only for stated preferences.",
            "Do not repeat a global never-claim in fit_line or reason detail. Do not make a claim forbidden for evidence cited by that reason or fit line.",
            "Only brainlayer, voicelayer, or cmuxlayer evidence may support an MCP claim; voice-agent-tool-calling is not MCP evidence.",
            "Never invent resume evidence, infer an unevidenced skill, or turn a tool/vendor integration into ownership of the tool/vendor.",
            "An explicit human verdict is authoritative: your recommendation must match it and may not override it.",
            "Fit line: exactly one candid sentence of at most 160 characters grounded in cited evidence.",
            "Fit-line evidence IDs must include the posting ID and at least one candidate evidence ID; cite only evidence that supports the fit line.",
            'If fit_tier is weak, fit_line MUST begin exactly "Weak fit —". Weak answers are expected; do not flatter.',
            "Allowed evidence IDs:",
            json.dumps(allowed_evidence_ids, ensure_ascii=False),
            "Safe fit profile (private names and paths removed):",
            json.dumps(profile, ensure_ascii=False, sort_keys=True),
            "Public posting:",
            json.dumps(public_posting, ensure_ascii=False, sort_keys=True),
        ]
    )


def _discover_codex() -> str:
    configured = os.environ.get("CODEX", "").strip()
    if configured:
        return configured
    discovered = shutil.which("codex")
    if discovered:
        return discovered
    raise RuntimeError("Codex subscription runner not found")


def _subscription_runner(prompt: str, schema: dict[str, object]) -> object:
    codex = _discover_codex()
    with tempfile.TemporaryDirectory(prefix="coach-job-feed-luna-") as temp_dir:
        schema_path = Path(temp_dir) / "schema.json"
        output_path = Path(temp_dir) / "annotation.json"
        schema_path.write_text(
            json.dumps(schema, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )
        command = [
            codex,
            "exec",
            "-m",
            "gpt-5.6-luna",
            "-c",
            f'model_reasoning_effort="{LUNA_REASONING_EFFORT}"',
            "--sandbox",
            "read-only",
            "--ephemeral",
            "--skip-git-repo-check",
            "--color",
            "never",
            "--output-schema",
            str(schema_path),
            "--output-last-message",
            str(output_path),
            "-",
        ]
        completed = subprocess.run(
            command,
            input=prompt,
            text=True,
            capture_output=True,
            timeout=180,
            check=False,
            cwd=REPO_ROOT,
        )
        if completed.returncode != 0:
            return {
                "status": "error",
                "exit_code": completed.returncode,
                "stderr": completed.stderr,
            }
        try:
            data = json.loads(output_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            data = None
        return {"status": "ok", "exit_code": 0, "data": data}


def _extract_data(result: object) -> dict[str, object] | None:
    if not isinstance(result, dict) or result.get("status") != "ok":
        return None
    if "exit_code" in result and result["exit_code"] not in (None, 0):
        return None
    data = result.get("data")
    return data if isinstance(data, dict) else None


# Existing validation flow is retained from source relocation; debt is tracked.
def _validated_annotation(  # skipcq: PY-R1000
    data: dict[str, object] | None,
    *,
    profile: dict[str, object],
    allowed_evidence_ids: set[str],
    posting_evidence_id: str,
    expected_recommendation: str | None,
) -> dict[str, object] | None:
    if data is None or set(data) != MODEL_FIELDS:
        return None
    employer_type = data.get("employer_type")
    seniority_real = data.get("seniority_real")
    fit_score = data.get("fit_score")
    fit_tier = data.get("fit_tier")
    recommendation = data.get("recommendation")
    reasons = data.get("reasons")
    fit_line = data.get("fit_line")
    fit_line_evidence_ids = data.get("fit_line_evidence_ids")
    constraints = profile.get("constraints")
    if not isinstance(constraints, dict):
        return None
    global_never_claims = constraints.get("global_never_claims")
    scoped_prohibitions = constraints.get("evidence_scoped_prohibitions")
    if not isinstance(global_never_claims, list) or not isinstance(
        scoped_prohibitions, dict
    ):
        return None

    def contains_forbidden(text: str, phrases: list[object]) -> bool:
        folded = text.casefold()
        return any(
            isinstance(phrase, str)
            and phrase.strip()
            and phrase.strip().casefold() in folded
            for phrase in phrases
        )

    if employer_type not in {"direct", "agency", "unknown"}:
        return None
    if seniority_real is not None and not isinstance(seniority_real, bool):
        return None
    if type(fit_score) is not int or not 0 <= fit_score <= 100:
        return None
    if fit_tier not in FIT_TIER_RANGES or fit_score not in FIT_TIER_RANGES[fit_tier]:
        return None
    if recommendation not in RECOMMENDATIONS:
        return None
    if (
        expected_recommendation is not None
        and recommendation != expected_recommendation
    ):
        return None
    if not isinstance(reasons, list) or len(reasons) != len(REASON_FACTORS):
        return None
    normalized_reasons: list[dict[str, object]] = []
    seen_factors: set[str] = set()
    for reason in reasons:
        if not isinstance(reason, dict) or set(reason) != {
            "factor",
            "basis",
            "assessment",
            "evidence_ids",
            "detail",
        }:
            return None
        factor = reason.get("factor")
        basis = reason.get("basis")
        assessment = reason.get("assessment")
        evidence_ids = reason.get("evidence_ids")
        detail = reason.get("detail")
        if factor not in REASON_FACTORS or factor in seen_factors:
            return None
        if basis != FACTOR_BASES[factor]:
            return None
        if assessment not in {"positive", "mixed", "negative", "unknown"}:
            return None
        if (
            not isinstance(evidence_ids, list)
            or not evidence_ids
            or any(not isinstance(item, str) or not item for item in evidence_ids)
            or not set(evidence_ids) <= allowed_evidence_ids
            or posting_evidence_id not in evidence_ids
        ):
            return None
        if basis == "posting" and evidence_ids != [posting_evidence_id]:
            return None
        candidate_evidence_ids = set(evidence_ids) - {posting_evidence_id}
        if basis == "comparison" and not candidate_evidence_ids:
            return None
        if not isinstance(detail, str):
            return None
        detail = " ".join(detail.split())
        if not detail or len(detail) > 200:
            return None
        if contains_forbidden(detail, global_never_claims):
            return None
        if basis == "posting" and re.search(
            r"\b(?:candidate|profile|resume)\b"
            r"|^\s*(?:built|shipped|uses|demonstrated|has|brings)\b"
            r"|\b(?:their|his|her)\s+(?:experience|skills?|background)\b",
            detail,
            re.I,
        ):
            return None
        for evidence_id in candidate_evidence_ids:
            prohibited = scoped_prohibitions.get(evidence_id, [])
            if not isinstance(prohibited, list) or contains_forbidden(
                detail, prohibited
            ):
                return None
        if re.search(r"\bMCP\b", detail, re.I) and not (
            candidate_evidence_ids & MCP_EVIDENCE_IDS
        ):
            return None
        seen_factors.add(factor)
        normalized_reasons.append(
            {
                "factor": factor,
                "basis": basis,
                "assessment": assessment,
                "evidence_ids": list(dict.fromkeys(evidence_ids)),
                "detail": detail,
            }
        )
    if seen_factors != set(REASON_FACTORS):
        return None
    if not isinstance(fit_line, str):
        return None
    if (
        not isinstance(fit_line_evidence_ids, list)
        or len(fit_line_evidence_ids) < 2
        or any(
            not isinstance(evidence_id, str) or not evidence_id
            for evidence_id in fit_line_evidence_ids
        )
        or len(fit_line_evidence_ids) != len(set(fit_line_evidence_ids))
        or not set(fit_line_evidence_ids) <= allowed_evidence_ids
        or posting_evidence_id not in fit_line_evidence_ids
    ):
        return None
    fit_line_candidate_evidence_ids = set(fit_line_evidence_ids) - {posting_evidence_id}
    if not fit_line_candidate_evidence_ids:
        return None
    fit_line = " ".join(fit_line.split())
    if not fit_line or len(fit_line) > 160:
        return None
    if contains_forbidden(fit_line, global_never_claims):
        return None
    for evidence_id in fit_line_candidate_evidence_ids:
        prohibited = scoped_prohibitions.get(evidence_id, [])
        if not isinstance(prohibited, list) or contains_forbidden(fit_line, prohibited):
            return None
    if re.search(r"\bMCP\b", fit_line, re.I) and not (
        fit_line_candidate_evidence_ids & MCP_EVIDENCE_IDS
    ):
        return None
    if fit_tier == "weak" and not fit_line.startswith("Weak fit —"):
        return None
    return {
        "employer_type": employer_type,
        "seniority_real": seniority_real,
        "fit_score": fit_score,
        "fit_tier": fit_tier,
        "recommendation": recommendation,
        "reasons": normalized_reasons,
        "fit_line": fit_line,
        "fit_line_evidence_ids": list(fit_line_evidence_ids),
        "luna_status": "ok",
    }


def annotate(
    posting: dict[str, object],
    *,
    runner: Runner | None = None,
    profile_path: Path = DEFAULT_PROFILE_PATH,
) -> dict[str, object] | None:
    """Return one validated annotation, invalid metadata, or None on failure."""

    try:
        profile = _load_safe_profile_contract(profile_path)
        prompt = _build_prompt(posting, profile)
        posting_evidence_id = f"posting:{str(posting.get('id', '')).strip()}"
        allowed_evidence_ids = (
            {posting_evidence_id}
            | PROFILE_EVIDENCE_IDS
            | {
                str(signal["evidence_id"])
                for signal in profile.get("fit_signals", [])
                if isinstance(signal, dict) and signal.get("evidence_id")
            }
        )
        expected_recommendation = _expected_human_recommendation(posting)
        execute = runner or _subscription_runner
        for _attempt in range(2):
            result = execute(prompt, LUNA_SCHEMA)
            if not isinstance(result, dict) or result.get("status") != "ok":
                return None
            annotation = _validated_annotation(
                _extract_data(result),
                profile=profile,
                allowed_evidence_ids=allowed_evidence_ids,
                posting_evidence_id=posting_evidence_id,
                expected_recommendation=expected_recommendation,
            )
            if annotation is not None:
                return annotation
        return _invalid_annotation()
    except Exception as error:
        LOGGER.warning(
            "Luna annotation unavailable for %s: %s", posting.get("id", ""), error
        )
        return None


# Existing calibration flow is retained from source relocation; debt is tracked.
def calibrate(  # skipcq: PY-R1000
    fixture: dict[str, object],
    *,
    runner: Runner | None = None,
    profile_path: Path = DEFAULT_PROFILE_PATH,
) -> dict[str, object]:
    """Run a read-only frozen decision snapshot and report exact pairwise outcomes."""

    if set(fixture) != {"fixture_schema_version", "snapshot", "cases"}:
        raise ValueError("calibration fixture fields are not supported")
    if fixture["fixture_schema_version"] != 2:
        raise ValueError("unsupported calibration fixture")

    snapshot = fixture["snapshot"]
    snapshot_fields = {
        "snapshot_id",
        "snapshot_version",
        "source_kind",
        "source_label",
        "exported_at",
        "reviewed_at",
        "source_checksum",
        "snapshot_checksum",
        "supabase_export_verified",
        "provenance_status",
        "provenance_blocker",
    }
    if not isinstance(snapshot, dict) or set(snapshot) != snapshot_fields:
        raise ValueError("calibration snapshot fields are not supported")

    def nonempty_string(value: object, field: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field} must be a non-empty string")
        return value.strip()

    if snapshot["snapshot_version"] != 2:
        raise ValueError("unsupported calibration snapshot version")
    nonempty_string(snapshot["snapshot_id"], "snapshot_id")
    nonempty_string(snapshot["source_label"], "source_label")
    if snapshot["source_kind"] not in {
        "reviewed_current_source",
        "verified_supabase_export",
    }:
        raise ValueError("unsupported calibration source kind")
    for field in ("exported_at", "reviewed_at"):
        timestamp = nonempty_string(snapshot[field], field)
        try:
            parsed = datetime.fromisoformat(timestamp)
        except ValueError as error:
            raise ValueError(f"{field} must be an ISO-8601 timestamp") from error
        if parsed.utcoffset() is None:
            raise ValueError(f"{field} must include a UTC offset")
    for field in ("source_checksum", "snapshot_checksum"):
        value = nonempty_string(snapshot[field], field)
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", value):
            raise ValueError(f"{field} must be a sha256 checksum")

    supabase_verified = snapshot["supabase_export_verified"]
    if type(supabase_verified) is not bool:
        raise ValueError("supabase_export_verified must be boolean")
    provenance_blocker = snapshot["provenance_blocker"]
    if supabase_verified:
        if (
            snapshot["source_kind"] != "verified_supabase_export"
            or snapshot["provenance_status"] != "verified"
            or provenance_blocker is not None
        ):
            raise ValueError("verified Supabase provenance is internally inconsistent")
    elif (
        snapshot["source_kind"] != "reviewed_current_source"
        or snapshot["provenance_status"] != "blocked"
        or not isinstance(provenance_blocker, str)
        or not provenance_blocker.strip()
    ):
        raise ValueError("unverified Supabase provenance must carry a blocker")

    cases = fixture["cases"]
    if not isinstance(cases, list) or not cases:
        raise ValueError("calibration fixture must contain cases")
    cases_checksum = hashlib.sha256(
        json.dumps(
            cases,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    if snapshot["snapshot_checksum"] != f"sha256:{cases_checksum}":
        raise ValueError("calibration snapshot checksum does not match cases")
    serialized_fixture = json.dumps(fixture, ensure_ascii=False, sort_keys=True)
    if any(
        re.search(pattern, serialized_fixture, re.I)
        for pattern in (
            r"/(?:Users|home)/",
            r"file://",
            r"(?<![A-Za-z])[A-Za-z]:[\\/]",
            r"raw_private_note",
            r"PRIVATE_RECRUITER_NOTE",
        )
    ):
        raise ValueError("calibration fixture contains private or path-like data")

    rows: list[dict[str, object]] = []
    seen_ids: set[str] = set()
    seen_record_keys: set[str] = set()
    seen_decision_ids: set[str] = set()
    seen_ranks: set[int] = set()
    for case in cases:
        case_fields = {
            "source_decision_id",
            "source_record_key",
            "human_verdict",
            "human_rank",
            "decision_basis",
            "pair_eligible",
            "decision_note",
            "posting",
        }
        if not isinstance(case, dict) or set(case) != case_fields:
            raise ValueError("calibration case fields are not supported")
        posting_value = case["posting"]
        posting_fields = {"id", "title", "company", "location", "url", "jd_text"}
        if not isinstance(posting_value, dict) or set(posting_value) != posting_fields:
            raise ValueError("each calibration case needs an exact public posting")
        posting = dict(posting_value)
        for field in posting_fields:
            nonempty_string(posting[field], f"posting.{field}")
        if not str(posting["url"]).startswith("https://"):
            raise ValueError("posting.url must use https")
        if len(str(posting["jd_text"])) < 100:
            raise ValueError("posting.jd_text must contain a reviewed public excerpt")

        posting_id = str(posting["id"]).strip()
        record_key = nonempty_string(case["source_record_key"], "source_record_key")
        decision_id = case["source_decision_id"]
        human_rank = case["human_rank"]
        human_verdict = case["human_verdict"]
        decision_basis = case["decision_basis"]
        pair_eligible = case["pair_eligible"]
        nonempty_string(case["decision_note"], "decision_note")
        if (
            posting_id in seen_ids
            or record_key in seen_record_keys
            or human_verdict not in {"applied", "skip"}
            or decision_basis not in {"fit", "workflow_override"}
            or type(pair_eligible) is not bool
        ):
            raise ValueError("invalid calibration case identity or human label")
        if decision_id is not None and (
            not isinstance(decision_id, str) or not decision_id.strip()
        ):
            raise ValueError("source_decision_id must be null or non-empty")
        if not supabase_verified and decision_id is not None:
            raise ValueError(
                "unverified Supabase provenance cannot claim durable decision IDs"
            )
        if supabase_verified and decision_id is None:
            raise ValueError(
                "verified Supabase provenance requires durable decision IDs"
            )
        if isinstance(decision_id, str):
            if decision_id in seen_decision_ids:
                raise ValueError("duplicate source_decision_id")
            seen_decision_ids.add(decision_id)
        if decision_basis == "workflow_override":
            if pair_eligible or human_rank is not None:
                raise ValueError("workflow override cannot be ranking-pair eligible")
        elif (
            not pair_eligible
            or type(human_rank) is not int
            or human_rank <= 0
            or human_rank in seen_ranks
        ):
            raise ValueError(
                "fit decisions need unique positive ranks and pair eligibility"
            )
        seen_ids.add(posting_id)
        seen_record_keys.add(record_key)
        if type(human_rank) is int:
            seen_ranks.add(human_rank)

        annotation = annotate(posting, runner=runner, profile_path=profile_path)
        status = (
            annotation.get("luna_status")
            if isinstance(annotation, dict)
            else "unavailable"
        )
        rows.append(
            {
                "posting_id": posting_id,
                "title": str(posting["title"]),
                "human_verdict": human_verdict,
                "human_rank": human_rank,
                "decision_basis": decision_basis,
                "pair_eligible": pair_eligible,
                "luna_status": status,
                "fit_score": (
                    annotation.get("fit_score")
                    if isinstance(annotation, dict) and status == "ok"
                    else None
                ),
                "fit_tier": (
                    annotation.get("fit_tier")
                    if isinstance(annotation, dict) and status == "ok"
                    else None
                ),
                "recommendation": (
                    annotation.get("recommendation")
                    if isinstance(annotation, dict) and status == "ok"
                    else None
                ),
                "fit_line": (
                    annotation.get("fit_line")
                    if isinstance(annotation, dict) and status == "ok"
                    else ""
                ),
            }
        )

    ranked = sorted(
        (row for row in rows if row["pair_eligible"]),
        key=lambda row: int(row["human_rank"]),
    )
    pairs: list[dict[str, object]] = []
    for higher, lower in combinations(ranked, 2):
        higher_score = higher["fit_score"]
        lower_score = lower["fit_score"]
        if type(higher_score) is not int or type(lower_score) is not int:
            outcome = "unavailable"
        elif higher_score > lower_score:
            outcome = "agreement"
        elif higher_score == lower_score:
            outcome = "tie"
        else:
            outcome = "disagreement"
        applicable_to_spec = (
            higher["decision_basis"] == "fit"
            and higher["human_verdict"] == "applied"
            and lower["decision_basis"] == "fit"
            and lower["human_verdict"] == "skip"
        )
        pairs.append(
            {
                "expected_higher": higher["posting_id"],
                "expected_lower": lower["posting_id"],
                "higher_score": higher_score,
                "lower_score": lower_score,
                "outcome": outcome,
                "comparison_basis": (
                    "applied_over_fit_mismatch_skip"
                    if applicable_to_spec
                    else "fit_rank"
                ),
                "applicable_to_spec": applicable_to_spec,
            }
        )

    eligible_applied = [
        row
        for row in rows
        if row["pair_eligible"]
        and row["decision_basis"] == "fit"
        and row["human_verdict"] == "applied"
    ]
    eligible_fit_skips = [
        row
        for row in rows
        if row["pair_eligible"]
        and row["decision_basis"] == "fit"
        and row["human_verdict"] == "skip"
    ]
    applicable_pairs = [pair for pair in pairs if pair["applicable_to_spec"]]
    available_applicable_pairs = [
        pair for pair in applicable_pairs if pair["outcome"] != "unavailable"
    ]
    blocked_requirements: list[str] = []
    if not supabase_verified:
        blocked_requirements.extend(
            [
                "supabase_export_unverified",
                "durable_decision_ids_unavailable",
            ]
        )
    if not eligible_applied:
        blocked_requirements.append("eligible_applied_case_unavailable")
    if not eligible_fit_skips:
        blocked_requirements.append("verified_fit_mismatch_skip_unavailable")
    if not applicable_pairs:
        blocked_requirements.append("applied_vs_fit_mismatch_pair_unavailable")
    if not available_applicable_pairs:
        blocked_requirements.append(
            "available_applied_vs_fit_mismatch_pair_unavailable"
        )
    excluded_cases = [
        {
            "posting_id": row["posting_id"],
            "decision_basis": row["decision_basis"],
            "reason": "pair_eligible_false",
        }
        for row in rows
        if not row["pair_eligible"]
    ]
    return {
        "snapshot_id": snapshot["snapshot_id"],
        "provenance": copy.deepcopy(snapshot),
        "provisional": bool(blocked_requirements),
        "spec_compliant": not blocked_requirements,
        "blocked_requirements": blocked_requirements,
        "case_count": len(rows),
        "eligible_case_count": len(ranked),
        "excluded_case_count": len(excluded_cases),
        "pair_count": len(pairs),
        "eligible_applied_case_count": len(eligible_applied),
        "eligible_fit_mismatch_skip_count": len(eligible_fit_skips),
        "applicable_pair_count": len(applicable_pairs),
        "available_applicable_pair_count": len(available_applicable_pairs),
        "agreement_count": sum(pair["outcome"] == "agreement" for pair in pairs),
        "disagreement_count": sum(
            pair["outcome"] in {"disagreement", "tie"} for pair in pairs
        ),
        "unavailable_pair_count": sum(
            pair["outcome"] == "unavailable" for pair in pairs
        ),
        "cases": rows,
        "excluded_cases": excluded_cases,
        "pairs": pairs,
    }


__all__ = ["LUNA_SCHEMA", "annotate", "calibrate"]
