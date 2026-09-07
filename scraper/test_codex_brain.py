from __future__ import annotations

import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from scraper import brain


OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "role_family": {"type": "string", "enum": ["backend", "other"]},
        "mentions_typescript": {"type": "boolean"},
    },
    "required": ["role_family", "mentions_typescript"],
    "additionalProperties": False,
}


def request() -> brain.BrainRequest:
    return brain.BrainRequest(
        "Classify this generic public TypeScript backend posting.",
        OUTPUT_SCHEMA,
    )


def install_runtime(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    process_runner,
) -> tuple[Path, list[str]]:
    auth_path = tmp_path / "source-auth.json"
    auth_path.write_text("test-only-placeholder", encoding="utf-8")
    verified: list[str] = []
    monkeypatch.setattr(
        brain, "_discover_codex", lambda: "/test/bin/codex", raising=False
    )
    monkeypatch.setattr(
        brain,
        "_verify_codex_version",
        lambda path, **_kwargs: verified.append(path),
        raising=False,
    )
    monkeypatch.setattr(
        brain, "_subscription_auth_path", auth_path.resolve, raising=False
    )
    monkeypatch.setattr(
        brain, "_run_codex_process", process_runner, raising=False
    )
    return auth_path, verified


def test_codex_dispatch_preserves_isolation_and_configured_provenance(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}

    def fake_process(command, **kwargs):
        output_path = Path(command[command.index("--output-last-message") + 1])
        schema_path = Path(command[command.index("--output-schema") + 1])
        isolated_home = Path(kwargs["env"]["CODEX_HOME"])
        captured.update(
            command=command,
            prompt=kwargs["stdin_text"],
            options=kwargs,
            schema=json.loads(schema_path.read_text(encoding="utf-8")),
            workspace=Path(kwargs["cwd"]),
            auth_target=(isolated_home / "auth.json").resolve(),
        )
        output_path.write_text(
            json.dumps({
                "role_family": "backend",
                "mentions_typescript": True,
            }),
            encoding="utf-8",
        )
        return SimpleNamespace(returncode=0)

    auth_path, verified = install_runtime(monkeypatch, tmp_path, fake_process)
    monkeypatch.setenv("JOB_RADAR_PRIVATE_SENTINEL", "must-not-reach-codex")

    result = brain.run_brain(
        request(),
        {
            "runtime.brain": "codex",
            "candidate.preferences": "PRIVATE_PROFILE_SENTINEL",
        },
        env={
            "BRAIN": "codex",
            "CODEX_MODEL": "gpt-test-public",
            "CODEX_REASONING_EFFORT": "high",
        },
        opener=lambda *_args, **_kwargs: pytest.fail("Codex used Ollama HTTP"),
        timeout_seconds=12,
    )

    command = captured["command"]
    options = captured["options"]
    assert verified == ["/test/bin/codex"]
    assert command[:2] == ["/test/bin/codex", "exec"]
    assert command[command.index("-m") + 1] == "gpt-test-public"
    assert 'model_reasoning_effort="high"' in command
    assert {"--strict-config", "--ignore-user-config", "--ignore-rules"} <= set(command)
    disabled_features = {
        command[index + 1]
        for index, argument in enumerate(command[:-1])
        if argument == "--disable"
    }
    assert {"shell_tool", "code_mode_host", "computer_use", "multi_agent"} <= disabled_features
    assert command[command.index("--sandbox") + 1] == "read-only"
    assert command[-1] == "-"
    assert 0 < options["timeout"] <= 12
    assert options["cwd"] == Path(command[command.index("-C") + 1])
    assert options["cwd"] != Path.cwd()
    assert options["stdout"] is subprocess.DEVNULL
    assert options["stderr"] is subprocess.DEVNULL
    assert "capture_output" not in options
    assert "JOB_RADAR_PRIVATE_SENTINEL" not in options["env"]
    assert captured["auth_target"] == auth_path.resolve()
    assert captured["schema"] == OUTPUT_SCHEMA
    assert captured["prompt"] == request().prompt
    assert "PRIVATE_PROFILE_SENTINEL" not in json.dumps(captured, default=str)
    assert not captured["workspace"].exists()
    assert result == brain.BrainResult(
        {"role_family": "backend", "mentions_typescript": True},
        "codex",
        "configured:gpt-test-public",
        request=request(),
    )


@pytest.mark.parametrize(
    "mode,error,match",
    [
        ("exit", brain.BrainTransportError, "exit code 7"),
        ("missing", brain.BrainResponseError, "output is missing"),
        ("invalid", brain.BrainResponseError, "invalid JSON"),
        ("oversized", brain.BrainResponseError, "byte limit"),
        ("schema", brain.BrainValidationError, "enum"),
    ],
)
def test_codex_output_and_exit_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    mode: str,
    error: type[brain.BrainError],
    match: str,
) -> None:
    def fake_process(command, **_kwargs):
        output_path = Path(command[command.index("--output-last-message") + 1])
        if mode == "exit":
            return SimpleNamespace(returncode=7)
        if mode == "invalid":
            output_path.write_bytes(b"not-json")
        elif mode == "oversized":
            output_path.write_bytes(b" " * (brain.MAX_RESPONSE_BYTES + 1))
        elif mode == "schema":
            output_path.write_text(
                '{"role_family":"frontend","mentions_typescript":true}',
                encoding="utf-8",
            )
        return SimpleNamespace(returncode=0)

    install_runtime(monkeypatch, tmp_path, fake_process)
    with pytest.raises(error, match=match):
        brain.run_brain(request(), env={"BRAIN": "codex"})


def test_codex_timeout_and_runtime_setup_use_brain_errors(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def timed_out(*_args, **_kwargs):
        raise subprocess.TimeoutExpired("codex", 3)

    install_runtime(monkeypatch, tmp_path, timed_out)
    with pytest.raises(brain.BrainTransportError, match="timed out"):
        brain.run_brain(request(), env={"BRAIN": "codex"}, timeout_seconds=3)

    monkeypatch.setattr(
        brain,
        "_discover_codex",
        lambda: (_ for _ in ()).throw(RuntimeError("private setup detail")),
    )
    with pytest.raises(brain.BrainConfigurationError, match="runtime is unavailable"):
        brain.run_brain(request(), env={"BRAIN": "codex"})


@pytest.mark.parametrize(
    "settings,match",
    [
        ({"CODEX_MODEL": "x" * 513}, "CODEX_MODEL"),
        ({"CODEX_REASONING_EFFORT": "urgent"}, "CODEX_REASONING_EFFORT"),
    ],
)
def test_codex_configuration_rejects_before_process(
    monkeypatch: pytest.MonkeyPatch,
    settings: dict[str, str],
    match: str,
) -> None:
    monkeypatch.setattr(
        brain,
        "_run_codex_process",
        lambda *_args, **_kwargs: pytest.fail("invalid config reached Codex"),
        raising=False,
    )
    with pytest.raises(brain.BrainConfigurationError, match=match):
        brain.run_brain(request(), env={"BRAIN": "codex", **settings})
