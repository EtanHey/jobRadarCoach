import json

import pytest

from scraper import brain_contract as brain
from scraper.annotate import LUNA_SCHEMA


def closed_schema(child):
    return {"type": "object", "properties": {"x": child},
            "required": ["x"], "additionalProperties": False}


def test_provider_precedence_and_invalid_settings():
    assert brain.resolve_brain({"runtime.brain": "codex"}, {"BRAIN": "ollama"}) == "ollama"
    assert brain.resolve_brain({"runtime.brain": "claude"}, {}) == "claude"
    assert brain.resolve_brain({}, {}) == "ollama"
    for profile, env in [({}, {"BRAIN": ""}), ({"runtime.brain": 42}, {}), ({}, {"BRAIN": "other"})]:
        with pytest.raises(brain.BrainConfigurationError):
            brain.resolve_brain(profile, env)


def test_request_bounds_and_closed_object():
    schema = closed_schema({"type": "string"})
    for prompt in (" ", "x" * (brain.MAX_PROMPT_BYTES + 1)):
        with pytest.raises(brain.BrainConfigurationError):
            brain.BrainRequest(prompt, schema)
    with pytest.raises(brain.BrainConfigurationError):
        brain.BrainRequest("public", {"type": "object", "properties": {}})
    with pytest.raises(brain.BrainConfigurationError):
        brain.BrainRequest("public", {**schema, "description": "x" * brain.MAX_SCHEMA_BYTES})


@pytest.mark.parametrize("child", [
    {"type": "string", "enum": None}, {"type": []},
    {"type": "object", "items": {"type": "string"}},
    {"type": "string", "$ref": "https://invalid.example/schema"},
    {"type": "string", "unknown": True},
])
def test_malformed_and_unsupported_schemas_fail_closed(child):
    with pytest.raises(brain.BrainConfigurationError):
        brain.BrainRequest("public", closed_schema(child))


def test_luna_schema_and_nullable_bounds_are_preserved():
    assert brain.BrainRequest("public", LUNA_SCHEMA).output_schema == LUNA_SCHEMA
    schema = closed_schema({"type": ["integer", "null"], "minimum": 0, "maximum": 100})
    brain.BrainRequest("public", schema)
    for value in [None, 0, 100]:
        brain._validate({"x": value}, schema)
    with pytest.raises(brain.BrainValidationError, match="maximum"):
        brain._validate({"x": 101}, schema)


def test_request_owns_schema_and_returns_nested_copies():
    schema = closed_schema({"type": "string"})
    request = brain.BrainRequest("public", schema)

    schema["properties"]["x"]["type"] = "integer"
    retrieved = request.output_schema
    retrieved["properties"]["x"]["$ref"] = "https://invalid.example/schema"
    retrieved["additionalProperties"] = True

    assert request.output_schema == closed_schema({"type": "string"})
    brain._validate({"x": "still valid"}, request.output_schema)
    with pytest.raises(brain.BrainValidationError, match="type"):
        brain._validate({"x": 1}, request.output_schema)


def test_result_requires_schema_validation_and_owns_nested_data():
    request = brain.BrainRequest(
        "public",
        closed_schema({
            "type": "object",
            "properties": {"label": {"type": "string"}},
            "required": ["label"],
            "additionalProperties": False,
        }),
    )
    payload = {"x": {"label": "owned"}}

    with pytest.raises(TypeError):
        brain.BrainResult(payload, "ollama", "qwen3:8b")
    with pytest.raises(brain.BrainValidationError, match="required"):
        brain.BrainResult({"x": {}}, "ollama", "qwen3:8b", request=request)
    with pytest.raises(brain.BrainValidationError, match="finite"):
        brain.BrainResult({"x": {"label": float("inf")}}, "ollama", "qwen3:8b",
                          request=request)
    with pytest.raises(brain.UnsupportedBrainError):
        brain.BrainResult(payload, "other", "qwen3:8b", request=request)
    with pytest.raises(brain.BrainConfigurationError, match="model"):
        brain.BrainResult(payload, "ollama", "\t\n", request=request)

    result = brain.BrainResult(payload, "ollama", "qwen3:8b", request=request)
    payload["x"]["label"] = "input mutation"
    retrieved = result.data
    retrieved["x"]["label"] = "getter mutation"

    assert result.data == {"x": {"label": "owned"}}
    assert result.brain == "ollama"
    assert result.model == "qwen3:8b"


def test_result_rejects_cyclic_input_as_validation_error():
    request = brain.BrainRequest("public", closed_schema({"type": "object"}))
    payload = {"x": {}}
    payload["x"]["cycle"] = payload
    with pytest.raises(brain.BrainValidationError, match="finite JSON"):
        brain.BrainResult(payload, "ollama", "model", request=request)


@pytest.mark.parametrize("child,value", [
    ({"type": "boolean", "enum": [1]}, True),
    ({"type": "array", "items": {"type": "boolean"}, "enum": [[1]]}, [True]),
    ({"type": "object", "properties": {"flag": {"type": "boolean"}},
      "enum": [{"flag": 1}]}, {"flag": True}),
])
def test_enum_equality_preserves_json_types(child, value):
    schema = closed_schema(child)
    brain.BrainRequest("public", schema)
    with pytest.raises(brain.BrainValidationError, match="enum"):
        brain._validate({"x": value}, schema)


def test_overflow_in_permitted_nested_values_fails_closed():
    schema = closed_schema({"type": "object", "additionalProperties": True})
    brain.BrainRequest("public", schema)
    with pytest.raises(brain.BrainValidationError, match="finite"):
        brain._validate(json.loads('{"x":{"nested":[1e400]}}'), schema)
