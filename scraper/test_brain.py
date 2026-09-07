from __future__ import annotations

import json

import os

from pathlib import Path

from urllib.error import HTTPError, URLError

import pytest

from scraper import brain

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "role_family": {"type": "string", "enum": ["backend", "frontend", "other"]},
        "mentions_typescript": {"type": "boolean"},
    },
    "required": ["role_family", "mentions_typescript"],
    "additionalProperties": False,
}

class Response:
    status = 200

    def __init__(self, body: object) -> None:
        self.body = body if isinstance(body, bytes) else json.dumps(body).encode()

    def __enter__(self): return self
    def __exit__(self, *_args): return None
    def read(self, limit: int) -> bytes: return self.body[:limit]

def request(prompt: str = "Classify this public TypeScript backend role.") -> brain.BrainRequest:
    return brain.BrainRequest(prompt=prompt, output_schema=OUTPUT_SCHEMA)

def test_request_and_timeout_bounds_fail_closed() -> None:
    for prompt in (" ", "x" * (brain.MAX_PROMPT_BYTES + 1)):
        with pytest.raises(brain.BrainConfigurationError, match="prompt"):
            brain.BrainRequest(prompt=prompt, output_schema=OUTPUT_SCHEMA)
    with pytest.raises(brain.BrainConfigurationError, match="closed object"):
        brain.BrainRequest(prompt="bounded", output_schema={"type": "object", "properties": {}})
    with pytest.raises(brain.BrainConfigurationError, match="timeout"):
        brain.run_brain(request(), {}, env={}, timeout_seconds=121)

def test_ollama_request_excludes_profile_and_returns_actual_provenance() -> None:
    captured = {}

    def opener(http_request, *, timeout):
        captured.update(url=http_request.full_url, timeout=timeout, body=json.loads(http_request.data))
        return Response({
            "model": "qwen2.5:7b-instruct", "done": True,
            "message": {"content": json.dumps({
                "role_family": "backend", "mentions_typescript": True,
            })},
        })

    result = brain.run_brain(
        request(),
        {"runtime.brain": "ollama", "candidate.preferences": "PRIVATE_PROFILE_SENTINEL"},
        env={}, opener=opener, timeout_seconds=12,
    )
    assert result == brain.BrainResult(
        data={"role_family": "backend", "mentions_typescript": True},
        brain="ollama", model="qwen2.5:7b-instruct", request=request(),
    )
    assert (captured["url"], captured["timeout"]) == ("http://127.0.0.1:11434/api/chat", 12)
    assert captured["body"]["format"] == OUTPUT_SCHEMA
    assert captured["body"]["stream"] is False
    assert "PRIVATE_PROFILE_SENTINEL" not in json.dumps(captured["body"])

@pytest.mark.parametrize("payload,error", [
    (b"not-json", brain.BrainResponseError),
    ({"done": True, "message": {"content": "{}"}}, brain.BrainResponseError),
    ({"model": "qwen", "done": True, "message": {"content": "not-json"}}, brain.BrainResponseError),
    ({
        "model": "qwen", "done": True,
        "message": {"content": '{"role_family":"backend","mentions_typescript":"yes"}'},
    }, brain.BrainValidationError),
])
def test_invalid_ollama_responses_fail_closed(payload, error) -> None:
    with pytest.raises(error):
        brain.run_brain(request(), {}, env={}, opener=lambda *_args, **_kwargs: Response(payload))

def test_nonfinite_result_hidden_in_permitted_nested_data_fails_closed() -> None:
    schema = {
        "type": "object",
        "properties": {
            "payload": {
                "type": "object", "properties": {}, "additionalProperties": True,
            },
        },
        "required": ["payload"],
        "additionalProperties": False,
    }
    with pytest.raises(brain.BrainValidationError, match="finite"):
        brain.run_brain(
            brain.BrainRequest("public fixture", schema), {}, env={},
            opener=lambda *_args, **_kwargs: Response({
                "model": "qwen", "done": True,
                "message": {"content": '{"payload":{"nested":[1e400]}}'},
            }),
        )

def test_http_and_timeout_fail_closed_without_fallback() -> None:
    def http_failure(http_request, **_kwargs):
        raise HTTPError(http_request.full_url, 503, "unavailable", {}, None)

    with pytest.raises(brain.BrainTransportError, match="HTTP 503"):
        brain.run_brain(request(), {}, env={}, opener=http_failure)
    with pytest.raises(brain.BrainTransportError, match="timed out"):
        brain.run_brain(
            request(), {}, env={},
            opener=lambda *_args, **_kwargs: (_ for _ in ()).throw(URLError(TimeoutError())),
        )

@pytest.mark.skipif(
    os.environ.get("JOBRADAR_RUN_OLLAMA_LIVE") != "1",
    reason="set JOBRADAR_RUN_OLLAMA_LIVE=1 for the native provider proof",
)
def test_native_ollama_positive_and_missing_model_failure() -> None:
    posting = json.loads(
        (Path(__file__).parent / "fixtures" / "luna-postings.json").read_text()
    )[0]
    live_request = request(
        f"Classify this public job. Title: {posting['title']}. Description: {posting['jd_text']}"
    )
    result = brain.run_brain(
        live_request, {}, env={"BRAIN": "ollama", "OLLAMA_MODEL": "qwen2.5:7b-instruct"},
        timeout_seconds=90,
    )
    assert (result.brain, result.model, set(result.data)) == (
        "ollama", "qwen2.5:7b-instruct", {"role_family", "mentions_typescript"},
    )
    with pytest.raises(brain.BrainTransportError, match="HTTP 404"):
        brain.run_brain(
            live_request, {},
            env={"BRAIN": "ollama", "OLLAMA_MODEL": "jobradar-model-does-not-exist"},
            timeout_seconds=10,
        )

def test_unimplemented_provider_has_no_fallback():
    with pytest.raises(brain.UnsupportedBrainError, match="codex"):
        brain.run_brain(request(), {}, env={"BRAIN": "codex"})

@pytest.mark.parametrize("model", ["x" * 513, "é" * 257])
def test_model_byte_limit_rejects_before_http(model):
    def forbidden_opener(*_args, **_kwargs):
        pytest.fail("oversized model reached HTTP")

    with pytest.raises(brain.BrainConfigurationError, match="OLLAMA_MODEL"):
        brain.run_brain(request(), env={"OLLAMA_MODEL": model}, opener=forbidden_opener)


def test_invalid_utf8_response_uses_brain_error():
    with pytest.raises(brain.BrainResponseError, match="invalid response JSON"):
        brain.run_brain(request(), env={}, opener=lambda *_a, **_k: Response(b"\xff"))


def test_direct_socket_timeout_uses_brain_error():
    def timed_out(*_args, **_kwargs):
        raise TimeoutError("socket inactivity")

    with pytest.raises(brain.BrainTransportError, match="timed out"):
        brain.run_brain(request(), env={}, opener=timed_out)
