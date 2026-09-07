"""Native Ollama and Codex transports for validated batch brain requests."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
from typing import Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from scraper.annotate import (
    LUNA_MODEL,
    LUNA_REASONING_EFFORT,
    _codex_exec_command,
    _discover_codex,
    _isolated_codex_environment,
    _subscription_auth_path,
)
from scraper.codex_process import (
    run_codex_process as _run_codex_process,
    verify_codex_version as _verify_codex_version,
)
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

DEFAULT_CODEX_MODEL = LUNA_MODEL

DEFAULT_CODEX_REASONING_EFFORT = LUNA_REASONING_EFFORT

CODEX_REASONING_EFFORTS = frozenset({"minimal", "low", "medium", "high", "xhigh"})

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
    if type(timeout_seconds) not in (int, float) or not 0 < timeout_seconds <= MAX_TIMEOUT_SECONDS:
        raise BrainConfigurationError("timeout must be between 0 and 120 seconds")
    if provider == "codex":
        return _run_codex(request, settings, timeout_seconds)
    if provider != "ollama":
        raise UnsupportedBrainError(f"brain provider '{provider}' is not implemented")
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


def _run_codex(
    request: BrainRequest,
    settings: Mapping[str, str],
    timeout_seconds: int | float,
) -> BrainResult:
    deadline = time.monotonic() + timeout_seconds
    model = _setting(settings, "CODEX_MODEL", DEFAULT_CODEX_MODEL)
    if len(model.encode("utf-8")) > MAX_MODEL_BYTES:
        raise BrainConfigurationError("CODEX_MODEL exceeds the byte limit")
    reasoning_effort = _setting(
        settings,
        "CODEX_REASONING_EFFORT",
        DEFAULT_CODEX_REASONING_EFFORT,
    ).casefold()
    if reasoning_effort not in CODEX_REASONING_EFFORTS:
        raise BrainConfigurationError("CODEX_REASONING_EFFORT is unsupported")
    try:
        codex = _discover_codex()
        auth_path = _subscription_auth_path()
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        raise BrainConfigurationError("Codex runtime is unavailable or unsupported") from error

    try:
        with tempfile.TemporaryDirectory(prefix="job-radar-codex-") as temp_dir:
            temp_root = Path(temp_dir)
            workspace = temp_root / "workspace"
            codex_home = temp_root / "codex-home"
            workspace.mkdir()
            codex_home.mkdir()
            (codex_home / "auth.json").symlink_to(auth_path)
            environment = _isolated_codex_environment(codex_home)
            try:
                _verify_codex_version(codex, cwd=workspace, env=environment,
                                      timeout=min(10, max(0, deadline - time.monotonic())))
            except RuntimeError as error:
                raise BrainConfigurationError("Codex runtime is unavailable or unsupported") from error
            schema_path = workspace / "schema.json"
            output_path = workspace / "result.json"
            schema_path.write_text(
                json.dumps(request.output_schema, ensure_ascii=False, sort_keys=True),
                encoding="utf-8",
            )
            command = _codex_exec_command(
                codex,
                workspace=workspace,
                schema_path=schema_path,
                output_path=output_path,
                model=model,
                reasoning_effort=reasoning_effort,
            )
            completed = _run_codex_process(
                command,
                input=request.prompt,
                text=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=max(0, deadline - time.monotonic()),
                check=False,
                cwd=workspace,
                env=environment,
            )
            if completed.returncode != 0:
                raise BrainTransportError(
                    f"Codex request failed with exit code {completed.returncode}"
                )
            raw = _read_codex_output(output_path)
    except subprocess.TimeoutExpired as error:
        raise BrainTransportError("Codex request timed out") from error
    except BrainError:
        raise
    except OSError as error:
        raise BrainTransportError("Codex request failed") from error

    data = _load_codex_json(raw)
    if not isinstance(data, dict):
        raise BrainValidationError("Codex structured result must be an object")
    return BrainResult(
        data,
        "codex",
        f"configured:{model}",
        request=request,
    )


def _read_codex_output(output_path: Path) -> bytes:
    try:
        if output_path.stat().st_size > MAX_RESPONSE_BYTES:
            raise BrainResponseError("Codex response exceeds the byte limit")
        with output_path.open("rb") as output_file:
            raw = output_file.read(MAX_RESPONSE_BYTES + 1)
    except FileNotFoundError as error:
        raise BrainResponseError("Codex output is missing") from error
    except BrainError:
        raise
    except OSError as error:
        raise BrainResponseError("Codex output could not be read") from error
    if len(raw) > MAX_RESPONSE_BYTES:
        raise BrainResponseError("Codex response exceeds the byte limit")
    return raw


def _load_codex_json(raw: bytes) -> object:
    def reject_constant(value: str) -> None:
        raise ValueError(value)

    try:
        return json.loads(raw.decode("utf-8"), parse_constant=reject_constant)
    except ValueError as error:
        raise BrainResponseError("Codex returned invalid JSON") from error


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
