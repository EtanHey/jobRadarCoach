"""Data-only batch brain requests, provider selection and JSON validation."""


from __future__ import annotations

from dataclasses import dataclass, field
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


@dataclass(frozen=True, init=False)
class BrainRequest:
    prompt: str
    _output_schema_json: str = field(repr=False)

    def __init__(self, prompt: str, output_schema: dict[str, object]) -> None:
        if not isinstance(prompt, str) or not prompt.strip():
            raise BrainConfigurationError("brain prompt must be a nonblank string")
        if len(prompt.encode("utf-8")) > MAX_PROMPT_BYTES:
            raise BrainConfigurationError("brain prompt exceeds the byte limit")
        encoded_schema, owned_schema = _owned_json(
            output_schema,
            BrainConfigurationError,
            "output schema must be JSON serializable",
        )
        if len(encoded_schema.encode("utf-8")) > MAX_SCHEMA_BYTES:
            raise BrainConfigurationError("output schema exceeds the byte limit")
        if not isinstance(owned_schema, dict):
            raise BrainConfigurationError("output schema must be a JSON object")
        try:
            Draft202012Validator.check_schema(owned_schema)
        except SchemaError as error:
            raise BrainConfigurationError("output schema is invalid") from error
        _check_schema_boundaries(owned_schema)
        if (
            owned_schema.get("type") != "object"
            or owned_schema.get("additionalProperties") is not False
        ):
            raise BrainConfigurationError("output schema must be a closed object")
        object.__setattr__(self, "prompt", prompt)
        object.__setattr__(self, "_output_schema_json", encoded_schema)

    @property
    def output_schema(self) -> dict[str, object]:
        schema = json.loads(self._output_schema_json)
        assert isinstance(schema, dict)
        return schema


@dataclass(frozen=True, init=False)
class BrainResult:
    _data_json: str = field(repr=False)
    brain: str
    model: str

    def __init__(
        self,
        data: dict[str, object],
        brain: str,
        model: str,
        *,
        request: BrainRequest,
    ) -> None:
        if not isinstance(request, BrainRequest):
            raise BrainConfigurationError("brain result requires its validated request")
        if not isinstance(brain, str) or brain not in SUPPORTED_BRAINS:
            raise UnsupportedBrainError("brain result provider is unsupported")
        if not isinstance(model, str) or not model.strip():
            raise BrainConfigurationError("brain result model must be a nonblank string")
        encoded_data, owned_data = _owned_json(
            data,
            BrainValidationError,
            "brain result must be finite JSON",
        )
        if not isinstance(owned_data, dict):
            raise BrainValidationError("brain result must be a JSON object")
        _validate(owned_data, request.output_schema)
        object.__setattr__(self, "_data_json", encoded_data)
        object.__setattr__(self, "brain", brain)
        object.__setattr__(self, "model", model)

    @property
    def data(self) -> dict[str, object]:
        value = json.loads(self._data_json)
        assert isinstance(value, dict)
        return value


def _owned_json(
    value: object,
    error_type: type[BrainError],
    message: str,
) -> tuple[str, object]:
    try:
        encoded = json.dumps(
            value, ensure_ascii=False, allow_nan=False, separators=(",", ":")
        )
        return encoded, json.loads(encoded)
    except (TypeError, ValueError) as error:
        raise error_type(message) from error


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
