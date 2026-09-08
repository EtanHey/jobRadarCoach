"""Concrete, ownership-safe services for the local ``./run`` supervisor."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shlex
import subprocess
from typing import Any, Callable, Sequence

from scripts.runtime_control import Probe, ProcessService, RuntimeContext, Service
from scripts.runtime_tailnet import TailscaleServeService


KUBECTL = ("kubectl", "--context", "orbstack", "-n", "job-radar-coach")


def _result(context: RuntimeContext, command: Sequence[str], *, timeout: float = 5):
    try:
        return context.run(command, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return None


def _json(context: RuntimeContext, command: Sequence[str]) -> dict[str, Any] | None:
    result = _result(context, command)
    if result is None or result.returncode:
        return None
    try:
        value = json.loads(result.stdout)
    except (json.JSONDecodeError, UnicodeError):
        return None
    return value if isinstance(value, dict) else None


def _http(context: RuntimeContext, url: str) -> bool:
    result = _result(context, ("curl", "-fsS", "-o", "/dev/null", "--max-time", "2", url))
    return result is not None and result.returncode == 0


def _processes(context: RuntimeContext, executable: str, *arguments: str) -> list[tuple[int, str]]:
    result = _result(context, ("ps", "-axo", "pid=,command="))
    matches: list[tuple[int, str]] = []
    if result is None or result.returncode:
        return matches
    for line in result.stdout.splitlines():
        pid_text, _, argv = line.strip().partition(" ")
        try:
            parts = shlex.split(argv)
        except ValueError:
            continue
        if (
            pid_text.isdigit() and parts and Path(parts[0]).name == executable
            and all(argument in parts[1:] for argument in arguments)
        ):
            matches.append((int(pid_text), argv))
    return matches


def _listener(context: RuntimeContext, port: int) -> tuple[int, str] | None:
    result = _result(context, ("lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"))
    if result is None or result.returncode:
        return None
    pids = {line.strip() for line in result.stdout.splitlines() if line.strip().isdigit()}
    if len(pids) != 1:
        return None
    pid = pids.pop()
    argv = _result(context, ("ps", "-ww", "-o", "command=", "-p", pid))
    if argv is None or argv.returncode or not argv.stdout.strip():
        return None
    return int(pid), argv.stdout.strip()


class RequirementService:
    """A shared prerequisite that this supervisor must never start or stop."""

    def __init__(self, name: str, check: Callable[[RuntimeContext], Probe]) -> None:
        self.name, self._check = name, check

    def probe(self, context: RuntimeContext) -> Probe:
        return self._check(context)

    def start(self, context: RuntimeContext) -> dict[str, Any]:
        detail = self.probe(context).detail or "not healthy"
        raise RuntimeError(f"{self.name} is a required borrowed service: {detail}")

    def owns(self, context: RuntimeContext, identity: dict[str, Any]) -> bool:
        return False

    def stop(self, context: RuntimeContext, identity: dict[str, Any]) -> None:
        raise RuntimeError(f"{self.name} is borrowed; refusing to stop it")


class SafeProcessService(ProcessService):
    """Process service that refuses duplicate or unfamiliar existing processes."""

    def __init__(self, *args, conflict: Callable[[RuntimeContext], str | None], prepare=None, finish=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._conflict, self._prepare, self._finish = conflict, prepare, finish

    def start(self, context: RuntimeContext) -> dict[str, Any]:
        conflict = self._conflict(context)
        if conflict:
            raise RuntimeError(conflict)
        if self._prepare:
            self._prepare()
        try:
            return super().start(context)
        finally:
            if self._finish:
                self._finish()


def _kubernetes(context: RuntimeContext) -> Probe:
    value = _json(context, ("kubectl", "--context", "orbstack", "get", "nodes", "-o", "json"))
    try:
        ready = any(
            condition.get("type") == "Ready" and condition.get("status") == "True"
            for item in value["items"] for condition in item["status"]["conditions"]
        )
    except (KeyError, TypeError):
        ready = False
    return Probe(ready, "orbstack node ready" if ready else "start OrbStack and enable Kubernetes")


def _supabase(context: RuntimeContext) -> Probe:
    try:
        config = (context.repo_root / "supabase" / "config.toml").read_text()
    except OSError:
        return Probe(False, "supabase/config.toml unavailable")
    if not re.search(r'^project_id\s*=\s*"jobRadarCoach"\s*$', config, re.MULTILINE):
        return Probe(False, "project_id is not jobRadarCoach")
    status = _json(context, ("supabase", "status", "-o", "json", "--workdir", str(context.repo_root)))
    return Probe(status is not None, "shared jobRadarCoach stack healthy" if status else "run supabase start for jobRadarCoach")


def _ollama(context: RuntimeContext) -> Probe:
    known = _processes(context, "ollama", "serve")
    healthy = len(known) == 1 and _http(context, "http://127.0.0.1:11434/api/tags")
    return Probe(healthy, "shared Ollama healthy" if healthy else "shared Ollama is absent or unidentified")


def _kokoro(context: RuntimeContext) -> Probe:
    result = _result(context, (
        "docker", "ps", "--filter", "publish=8881", "--format", "{{json .}}",
    ))
    rows = [] if result is None or result.returncode else result.stdout.lower().splitlines()
    known = len(rows) == 1 and "kokoro" in rows[0]
    healthy = known and _http(context, "http://127.0.0.1:8881/v1/models")
    return Probe(healthy, "shared Kokoro healthy" if healthy else "shared Kokoro container is absent or unidentified")


def _deployment(name: str, *, livekit: bool = False) -> Callable[[RuntimeContext], Probe]:
    def check(context: RuntimeContext) -> Probe:
        result = _result(context, (*KUBECTL, "rollout", "status", f"deployment/{name}", "--timeout=1s"))
        if result is None or result.returncode:
            return Probe(False, f"deployment/{name} is not ready")
        if livekit:
            service = _json(context, (*KUBECTL, "get", "service/livekit", "-o", "json"))
            ports = {(item.get("port"), item.get("protocol", "TCP")) for item in (service or {}).get("spec", {}).get("ports", [])}
            if not {(7880, "TCP"), (7881, "TCP"), (50000, "UDP")} <= ports:
                return Probe(False, "service/livekit ports do not match the voice contract")
            config = _json(context, (*KUBECTL, "get", "configmap/livekit-advertise", "-o", "json"))
            tail_ip = _result(context, ("tailscale", "ip", "-4"))
            expected = "" if tail_ip is None or tail_ip.returncode else tail_ip.stdout.strip()
            if not expected or (config or {}).get("data", {}).get("node_ip") != expected:
                return Probe(False, "livekit-advertise node_ip does not match Tailscale")
            deployment = _json(context, (*KUBECTL, "get", "deployment/livekit", "-o", "json"))
            containers = (deployment or {}).get("spec", {}).get("template", {}).get("spec", {}).get("containers", [])
            env = [item for container in containers for item in container.get("env", [])]
            node_ip = next((item for item in env if item.get("name") == "NODE_IP"), {})
            reference = node_ip.get("valueFrom", {}).get("configMapKeyRef", {})
            if reference != {"name": "livekit-advertise", "key": "node_ip"}:
                return Probe(False, "deployment/livekit NODE_IP is not wired to livekit-advertise")
        return Probe(True, f"deployment/{name} ready")
    return check


def _identified_http_process(
    context: RuntimeContext, port: int, url: str, *tokens: str,
) -> Probe:
    listener = _listener(context, port)
    try:
        parts = [] if listener is None else shlex.split(listener[1])
    except ValueError:
        parts = []
    healthy = bool(
        parts and Path(parts[0]).name == tokens[0]
        and all(token in parts[1:] for token in tokens[1:]) and _http(context, url)
    )
    return Probe(healthy, "identified listener healthy" if healthy else f"port {port} is absent or unfamiliar")


def _agent_probe(log_path: Path, starting: list[bool]) -> Callable[[RuntimeContext], Probe]:
    def check(context: RuntimeContext) -> Probe:
        processes = _processes(context, "python", "agent/main.py", "console")
        try:
            ready = "starting worker" in log_path.read_text(encoding="utf-8")
        except OSError:
            ready = False
        healthy = len(processes) == 1 and ready if starting[0] else len(processes) == 1
        detail = "owned console agent startup marker observed" if starting[0] and ready else (
            "console agent alive; readiness and QA mode unverified"
        )
        return Probe(healthy, detail if healthy else "console agent readiness not proven")
    return check


def _bridge_probe(context: RuntimeContext) -> Probe:
    http, rtc = _listener(context, 17880), _listener(context, 17881)
    try:
        parts = [] if http is None else shlex.split(http[1])
    except ValueError:
        parts = []
    healthy = (
        http is not None and rtc is not None and http[0] == rtc[0]
        and parts and Path(parts[0]).name == "node"
        and (
            parts[-1] == "docs.local/collabs/voice-network-bridge.cjs"
            or Path(parts[-1]) == context.repo_root / "scripts" / "livekit_bridge.cjs"
        )
        and _http(context, "http://127.0.0.1:17880/")
    )
    return Probe(healthy, "voice loopback bridge healthy" if healthy else "voice bridge absent or unfamiliar")


def _port_conflict(port: int) -> Callable[[RuntimeContext], str | None]:
    def check(context: RuntimeContext) -> str | None:
        listener = _listener(context, port)
        if listener is None:
            return None
        return f"port {port} already has an unhealthy or unfamiliar listener"
    return check


def build_services(context: RuntimeContext) -> Sequence[Service]:
    if getattr(context, "qa_mode", False):
        return [RequirementService(
            "qa-runtime",
            lambda _context: Probe(False, "room-mode agent receipt and owned QA proxy are not installed"),
        )]
    whisper_port = int(os.environ.get("VOICE_STT_PORT", "8912"))
    whisper_model = Path(os.environ.get(
        "VOICE_STT_MODEL", "~/.cache/whisper/ggml-small.bin",
    )).expanduser()
    agent_log = context.state_dir / "agent.log"
    agent_starting = [False]
    status = _json(context, ("supabase", "status", "-o", "json", "--workdir", str(context.repo_root))) or {}
    database_url = status.get("DB_URL")
    agent_env = {"AGENT_LOG_FILE": str(agent_log)}
    if isinstance(database_url, str) and database_url:
        agent_env["DATABASE_URL"] = database_url
    if "VOICE_STT_PORT" in os.environ:
        agent_env["STT_URL"] = f"http://127.0.0.1:{whisper_port}/inference"
    return [
        RequirementService("kubernetes", _kubernetes),
        RequirementService("supabase", _supabase),
        RequirementService("ollama", _ollama),
        RequirementService("kokoro", _kokoro),
        RequirementService("livekit", _deployment("livekit", livekit=True)),
        RequirementService("ui", _deployment("ui")),
        SafeProcessService(
            "whisper",
            ("/opt/homebrew/bin/whisper-server", "-m", str(whisper_model), "--host", "127.0.0.1", "--port", str(whisper_port), "-l", os.environ.get("VOICE_STT_LANGUAGE", "en")),
            lambda ctx: _identified_http_process(ctx, whisper_port, f"http://127.0.0.1:{whisper_port}/", "whisper-server", "--port", str(whisper_port)),
            conflict=_port_conflict(whisper_port),
        ),
        SafeProcessService(
            "ui-forward", (*KUBECTL, "port-forward", "service/ui", "3410:3000"),
            lambda ctx: _identified_http_process(ctx, 3410, "http://127.0.0.1:3410/api/jobs?limit=1", "kubectl", "port-forward", "service/ui", "3410:3000"),
            conflict=_port_conflict(3410),
        ),
        SafeProcessService(
            "livekit-bridge", ("node", str(context.repo_root / "scripts" / "livekit_bridge.cjs")),
            _bridge_probe,
            conflict=lambda ctx: "voice bridge port conflict" if _listener(ctx, 17880) or _listener(ctx, 17881) else None,
        ),
        TailscaleServeService(),
        SafeProcessService(
            "agent", (str(context.repo_root / ".venv-agent" / "bin" / "python"), "agent/main.py", "console"),
            _agent_probe(agent_log, agent_starting), cwd=context.repo_root,
            env=agent_env, startup_timeout=30,
            conflict=lambda ctx: (
                "DATABASE_URL unavailable from supabase status" if not database_url
                else "multiple console agents exist"
                if len(_processes(ctx, "python", "agent/main.py", "console")) > 1
                else None
            ),
            prepare=lambda: (agent_log.unlink(missing_ok=True), agent_starting.__setitem__(0, True)),
            finish=lambda: agent_starting.__setitem__(0, False),
        ),
    ]
