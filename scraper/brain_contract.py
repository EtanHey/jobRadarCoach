"""Data-only batch brain requests, provider selection and JSON validation."""


from __future__ import annotations

from dataclasses import dataclass
import json
import math
import os
from typing import Mapping

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError


SUPPORTED_BRAINS = frozenset({"ollama", "codex", "claude", "cursor-agent"})


MAX_PROMPT_BYTES = 32_000


MAX_SCHEMA_BYTES = 16_384


_SCHEMA_KEYS = frozenset({
    "type", "properties", "required", "additionalProperties", "items", "enum",
    "minimum", "maximum", "minLength", "maxLength", "minItems", "maxItems",
    "description", "title",
})


class BrainError(RuntimeError): ...


class BrainConfigurationError(BrainError): ...


class UnsupportedBrainError(BrainConfigurationError): ...


class BrainTransportError(BrainError): ...


class BrainResponseError(BrainError): ...


class BrainValidationError(BrainResponseError): ...


@dataclass(frozen=True)
class BrainRequest:
    prompt: str
    output_schema: dict[str, object]

    def __post_init__(self) -> None:
        if not isinstance(self.prompt, str) or not self.prompt.strip():
            raise BrainConfigurationError("brain prompt must be a nonblank string")
        if len(self.prompt.encode("utf-8")) > MAX_PROMPT_BYTES:
            raise BrainConfigurationError("brain prompt exceeds the byte limit")
        try:
            encoded_schema = json.dumps(
                self.output_schema, ensure_ascii=False, allow_nan=False, separators=(",", ":")
            ).encode("utf-8")
        except (TypeError, ValueError) as error:
            raise BrainConfigurationError("output schema must be JSON serializable") from error
        if len(encoded_schema) > MAX_SCHEMA_BYTES:
            raise BrainConfigurationError("output schema exceeds the byte limit")
        try:
            Draft202012Validator.check_schema(self.output_schema)
        except SchemaError as error:
            raise BrainConfigurationError("output schema is invalid") from error
        _check_schema_boundaries(self.output_schema)
        if (
            self.output_schema.get("type") != "object"
            or self.output_schema.get("additionalProperties") is not False
        ):
            raise BrainConfigurationError("output schema must be a closed object")


@dataclass(frozen=True)
class BrainResult:
    data: dict[str, object]
    brain: str
    model: str


def _check_schema_boundaries(schema: object, path: str = "$") -> None:
    if not isinstance(schema, dict):
        raise BrainConfigurationError(f"schema at {path} must be an object")
    unknown = set(schema).difference(_SCHEMA_KEYS)
    if unknown:
        raise BrainConfigurationError(f"unsupported schema keys at {path}: {sorted(unknown)}")
    declared = schema.get("type")
    kinds = {declared} if isinstance(declared, str) else set(declared or [])
    if not kinds:
        raise BrainConfigurationError(f"schema at {path} must declare a type")
    keyword_types = {
        "properties": {"object"}, "required": {"object"},
        "additionalProperties": {"object"},
        "items": {"array"}, "minItems": {"array"}, "maxItems": {"array"},
        "minLength": {"string"}, "maxLength": {"string"},
        "minimum": {"integer", "number"}, "maximum": {"integer", "number"},
    }
    for keyword, valid_types in keyword_types.items():
        if keyword in schema and kinds.isdisjoint(valid_types):
            raise BrainConfigurationError(f"schema keyword {keyword} does not match type at {path}")
    properties = schema.get("properties", {})
    if isinstance(properties, dict):
        for key, child in properties.items():
            _check_schema_boundaries(child, f"{path}.{key}")
    if "items" in schema:
        _check_schema_boundaries(schema["items"], f"{path}[]")
    additional = schema.get("additionalProperties")
    if isinstance(additional, dict):
        _check_schema_boundaries(additional, f"{path}.*")


def _ensure_finite(value: object, error_type: type[BrainResponseError]) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise error_type("decoded JSON numbers must be finite")
    if isinstance(value, dict):
        for child in value.values():
            _ensure_finite(child, error_type)
    elif isinstance(value, list):
        for child in value:
            _ensure_finite(child, error_type)


def _validate(value: object, schema: dict[str, object]) -> None:
    _ensure_finite(value, BrainValidationError)
    try:
        Draft202012Validator(schema).validate(value)
    except ValidationError as error:
        keyword = error.validator if isinstance(error.validator, str) else "constraint"
        raise BrainValidationError(f"Ollama result failed JSON schema validation ({keyword})") from error


def resolve_brain(
    profile_snapshot: Mapping[str, object] | None = None,
    env: Mapping[str, str] | None = None,
) -> str:
    settings = os.environ if env is None else env
    if "BRAIN" in settings:
        value = settings["BRAIN"]
    elif profile_snapshot is not None and "runtime.brain" in profile_snapshot:
        value = profile_snapshot["runtime.brain"]
    else:
        value = "ollama"
    if not isinstance(value, str) or not value.strip():
        raise BrainConfigurationError("brain provider must be a nonblank string")
    provider = value.strip().casefold()
    if provider not in SUPPORTED_BRAINS:
        raise BrainConfigurationError(f"unknown brain provider: {provider}")
    return provider
