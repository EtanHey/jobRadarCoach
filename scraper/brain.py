"""Native Ollama transport for validated batch brain requests."""
from __future__ import annotations

import json
import os
from typing import Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from scraper.brain_contract import (
    BrainError,
    BrainConfigurationError,
    UnsupportedBrainError,
    BrainTransportError,
    BrainResponseError,
    BrainValidationError,
    BrainRequest,
    BrainResult,
    resolve_brain,
    SUPPORTED_BRAINS,
    MAX_PROMPT_BYTES,
    MAX_SCHEMA_BYTES,
    _ensure_finite,
    _validate,
)

__all__ = ['BrainError', 'BrainConfigurationError', 'UnsupportedBrainError', 'BrainTransportError', 'BrainResponseError', 'BrainValidationError', 'BrainRequest', 'BrainResult', 'resolve_brain', 'SUPPORTED_BRAINS', 'MAX_PROMPT_BYTES', 'MAX_SCHEMA_BYTES', 'run_brain']


DEFAULT_OLLAMA_BASE_URL = "http://127.0.0.1:11434"

DEFAULT_OLLAMA_MODEL = "qwen2.5:7b-instruct"

MAX_MODEL_BYTES = 512

MAX_RESPONSE_BYTES = 64_000

MAX_TIMEOUT_SECONDS = 120

def _setting(settings: Mapping[str, str], name: str, default: str) -> str:
    if name not in settings:
        return default
    value = settings[name]
    if not isinstance(value, str) or not value.strip():
        raise BrainConfigurationError(f"{name} must be a nonblank string")
    return value.strip()

def _endpoint(base_url: str) -> str:
    parsed = urlsplit(base_url)
    if (
        parsed.scheme not in ("http", "https")
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in ("", "/")
    ):
        raise BrainConfigurationError("OLLAMA_BASE_URL must be an origin without credentials")
    return base_url.rstrip("/") + "/api/chat"

def _load_json(raw: bytes, label: str) -> object:
    def reject_constant(value: str) -> None:
        raise ValueError(value)

    try:
        return json.loads(raw.decode("utf-8"), parse_constant=reject_constant)
    except ValueError as error:
        raise BrainResponseError(f"Ollama returned invalid {label} JSON") from error

def run_brain(
    request: BrainRequest,
    profile_snapshot: Mapping[str, object] | None = None,
    *,
    env: Mapping[str, str] | None = None,
    opener: Callable[..., object] = urlopen,
    timeout_seconds: int | float = 60,
) -> BrainResult:
    settings = os.environ if env is None else env
    provider = resolve_brain(profile_snapshot, settings)
    if provider != "ollama":
        raise UnsupportedBrainError(f"brain provider '{provider}' is not implemented")
    if type(timeout_seconds) not in (int, float) or not 0 < timeout_seconds <= MAX_TIMEOUT_SECONDS:
        raise BrainConfigurationError("timeout must be between 0 and 120 seconds")
    model = _setting(settings, "OLLAMA_MODEL", DEFAULT_OLLAMA_MODEL)
    if len(model.encode("utf-8")) > MAX_MODEL_BYTES:
        raise BrainConfigurationError("OLLAMA_MODEL exceeds the byte limit")
    endpoint = _endpoint(_setting(settings, "OLLAMA_BASE_URL", DEFAULT_OLLAMA_BASE_URL))
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": request.prompt}],
        "stream": False,
        "format": request.output_schema,
        "options": {"temperature": 0, "num_predict": 512},
    }
    http_request = Request(
        endpoint,
        data=json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with opener(http_request, timeout=timeout_seconds) as response:
            status = getattr(response, "status", 200)
            if type(status) is not int or not 200 <= status <= 299:
                raise BrainTransportError(f"Ollama request failed with HTTP {status}")
            raw = response.read(MAX_RESPONSE_BYTES + 1)
    except HTTPError as error:
        raise BrainTransportError(f"Ollama request failed with HTTP {error.code}") from error
    except TimeoutError as error:
        raise BrainTransportError("Ollama request timed out") from error
    except URLError as error:
        message = "Ollama request timed out" if isinstance(error.reason, TimeoutError) else "Ollama request failed"
        raise BrainTransportError(message) from error
    except OSError as error:
        raise BrainTransportError("Ollama request failed") from error
    return _parse_response(raw, request)


def _parse_response(raw: bytes, request: BrainRequest) -> BrainResult:
    if not isinstance(raw, bytes) or len(raw) > MAX_RESPONSE_BYTES:
        raise BrainResponseError("Ollama response exceeds the byte limit")

    envelope = _load_json(raw, "response")
    _ensure_finite(envelope, BrainResponseError)
    if not isinstance(envelope, dict) or envelope.get("done") is not True:
        raise BrainResponseError("Ollama response is incomplete")
    actual_model = envelope.get("model")
    message = envelope.get("message")
    if not isinstance(actual_model, str) or not actual_model.strip() or not isinstance(message, dict):
        raise BrainResponseError("Ollama response lacks provenance or message")
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise BrainResponseError("Ollama response lacks structured content")
    data = _load_json(content.encode("utf-8"), "content")
    if not isinstance(data, dict):
        raise BrainValidationError("Ollama structured result must be an object")
    _validate(data, request.output_schema)
    return BrainResult(data=data, brain="ollama", model=actual_model.strip(), request=request)
