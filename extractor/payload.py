"""Validation and construction of owned extraction payloads."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
import json
import re

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from extractor.core import _schema
from extractor.evidence import validate_facts


_FACT_FIELDS = {"location", "remote", "seniority", "stack", "salary"}
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class Payload:
    brain: str
    model: str
    extractor_version: str
    schema_sha256: str
    jd_sha256: str
    fingerprint: str
    facts: dict[str, object]

    def metadata(self) -> tuple[object, ...]:
        return (
            self.brain, self.model, self.extractor_version, self.schema_sha256,
            self.jd_sha256, self.fingerprint, self.facts,
        )


def require_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"extraction {field} must be a nonblank string")
    return value


def require_sha256(value: object, field: str) -> str:
    text = require_text(value, field)
    if not _SHA256_RE.fullmatch(text):
        raise ValueError(f"extraction {field} must be a lowercase SHA-256")
    return text


def fingerprint(
    brain: str,
    model: str,
    extractor_version: str,
    schema_sha256: str,
    jd_sha256: str,
) -> str:
    identity = {
        "brain": brain,
        "extractor_version": extractor_version,
        "jd_sha256": jd_sha256,
        "model": model,
        "schema_sha256": schema_sha256,
    }
    encoded = json.dumps(identity, separators=(",", ":"), sort_keys=True).encode()
    return hashlib.sha256(encoded).hexdigest()


def _owned_facts(facts: object, captured_raw_jd: str) -> dict[str, object]:
    if not isinstance(facts, dict) or set(facts) != _FACT_FIELDS:
        raise ValueError("extraction facts must contain exactly the supported fields")
    try:
        owned = json.loads(json.dumps(facts, ensure_ascii=False, allow_nan=False))
    except (TypeError, ValueError) as error:
        raise ValueError("extraction facts must be finite JSON") from error
    try:
        Draft202012Validator(_schema()).validate(owned)
        validate_facts(owned, captured_raw_jd)
    except (AssertionError, KeyError, TypeError, ValidationError) as error:
        raise ValueError("extraction facts have an invalid shape") from error
    if any(
        owned[field]["value"] is not None
        and not isinstance(owned[field]["value"], str)
        for field in ("location", "seniority", "salary")
    ):
        raise ValueError("extraction text fact values must be text or null")
    return owned


def build_payload(
    extraction: Mapping[str, object], captured_raw_jd: str
) -> Payload:
    if set(extraction) != {
        "brain", "model", "extractor_version", "schema_sha256", "jd_sha256",
        "fingerprint", "facts",
    }:
        raise ValueError("extraction result has an invalid shape")
    brain = require_text(extraction["brain"], "brain")
    model = require_text(extraction["model"], "model")
    version = require_text(extraction["extractor_version"], "extractor_version")
    schema_sha256 = require_sha256(extraction["schema_sha256"], "schema_sha256")
    jd_sha256 = require_sha256(extraction["jd_sha256"], "jd_sha256")
    result_fingerprint = require_sha256(extraction["fingerprint"], "fingerprint")
    if hashlib.sha256(captured_raw_jd.encode()).hexdigest() != jd_sha256:
        raise ValueError("extraction jd_sha256 does not match the captured JD")
    expected = fingerprint(brain, model, version, schema_sha256, jd_sha256)
    if result_fingerprint != expected:
        raise ValueError("extraction fingerprint does not match its identity")
    facts = _owned_facts(extraction["facts"], captured_raw_jd)
    return Payload(
        brain, model, version, schema_sha256, jd_sha256, result_fingerprint, facts
    )
