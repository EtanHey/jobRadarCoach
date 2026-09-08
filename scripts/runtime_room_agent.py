"""Prepared ownership-safe normal LiveKit room worker adapter."""

from __future__ import annotations

import base64
import binascii
import json
import os
from pathlib import Path
import shlex
import subprocess
from typing import Callable

from scripts.runtime_verifier_source import pinned_verifier_source
from scripts.runtime_process import Identity, Probe, ProcessService, RuntimeContext
from scripts.runtime_qa_config import resolve_qa_urls


KUBECTL = ("kubectl", "--context", "orbstack", "-n", "job-radar-coach")
VERIFIER_SHA256 = "0c35e739ccaab2f3c9000098f51854ea209f2095ec7e46674e28a8a313928f8d"
Verifier = Callable[[RuntimeContext, Path, str], Probe]


def _receipt_pid(path: Path) -> int | None:
    try:
        pid = json.loads(path.read_text())["process"]["pid"]
    except (OSError, KeyError, TypeError, json.JSONDecodeError):
        return None
    return pid if isinstance(pid, int) and not isinstance(pid, bool) and pid > 0 else None


def _agent_processes(context: RuntimeContext) -> dict[int, bool] | None:
    try:
        result = context.run(("ps", "-axo", "pid=,command="), timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode:
        return None
    found: dict[int, bool] = {}
    script = context.repo_root / "agent/main.py"
    interpreter = context.repo_root / ".venv-agent/bin/python"
    for line in result.stdout.splitlines():
        pid_text, _, command = line.strip().partition(" ")
        try:
            parts = shlex.split(command)
        except ValueError:
            parts = command.split()
        if (
            not pid_text.isdigit() or len(parts) < 2
            or not Path(parts[0]).name.startswith("python")
            or Path(parts[1]).name != "main.py"
        ):
            continue
        pid = int(pid_text)
        try:
            cwd = context.run(("lsof", "-a", "-p", str(pid), "-d", "cwd", "-Fn"), timeout=5)
            paths = [line[1:] for line in cwd.stdout.splitlines() if line.startswith("n")]
        except (OSError, subprocess.SubprocessError):
            return None
        if cwd.returncode or len(paths) != 1:
            return None
        try:
            same_repo = Path(paths[0]).samefile(context.repo_root)
        except OSError:
            return None
        if not same_repo:
            continue
        candidate_interpreter = Path(parts[0]) if Path(parts[0]).is_absolute() else Path(paths[0]) / parts[0]
        candidate_script = Path(parts[1]) if Path(parts[1]).is_absolute() else Path(paths[0]) / parts[1]
        try:
            known_interpreter = candidate_interpreter.samefile(interpreter)
            known_script = candidate_script.samefile(script)
        except OSError:
            known_interpreter = known_script = False
        found[pid] = (
            len(parts) == 3 and known_interpreter and known_script
            and parts[2] in {"dev", "start"}
        )
    return found


def _verifier_result(result: subprocess.CompletedProcess[str]) -> Probe:
    try:
        value = json.loads(result.stdout)
    except (TypeError, json.JSONDecodeError):
        value = None
    if (
        result.returncode == 0 and result.stderr == "" and isinstance(value, dict)
        and set(value) == {"status", "mode", "worker_id"}
        and value.get("status") == "READY" and value.get("mode") == "normal"
        and isinstance(value.get("worker_id"), str) and value["worker_id"]
    ):
        return Probe(True, f"verified normal worker {value['worker_id']}")
    if (
        result.returncode != 0 and isinstance(value, dict)
        and set(value) == {"status", "reason"} and value.get("status") == "NOT_READY"
        and isinstance(value.get("reason"), str) and value["reason"].replace("_", "").isalnum()
    ):
        return Probe(False, f"normal NOT READY: {value['reason']}")
    return Probe(False, "normal NOT READY: verifier output invalid")


class RoomAgentService:
    """Borrows one verified normal worker or owns one exact ``start`` process."""

    name = "room-agent"

    def __init__(self, receipt_path: Path | None = None,
                 url_provider: Callable[[RuntimeContext], str] | None = None,
                 verifier: Verifier | None = None) -> None:
        self._external_receipt = receipt_path
        self._url_provider = url_provider
        self._verifier = verifier or self._default_verify
        self._selected_receipt: Path | None = None
        self._process: ProcessService | None = None

    @staticmethod
    def _owned_path(context: RuntimeContext) -> Path:
        return context.state_dir / "room-agent-receipt.json"

    def _external_path(self, context: RuntimeContext) -> Path:
        return self._external_receipt or Path(os.environ.get(
            "AGENT_NORMAL_RECEIPT_FILE", context.repo_root / "docs.local/voice-normal-agent-receipt.json",
        ))

    @staticmethod
    def _qa_path(context: RuntimeContext) -> Path:
        return Path(os.environ.get(
            "VOICE_QA_RECEIPT_FILE", context.repo_root / "docs.local/voice-qa-agent-receipt.json",
        ))

    def _paths_distinct(self, context: RuntimeContext, normal: Path) -> bool:
        try:
            return normal.resolve() != self._qa_path(context).resolve()
        except (OSError, RuntimeError):
            return False

    def receipt_path(self, context: RuntimeContext) -> Path:
        return self._selected_receipt or self._external_path(context)

    def _expected_url(self, context: RuntimeContext) -> str:
        return self._url_provider(context) if self._url_provider else (
            resolve_qa_urls(context).expected_livekit_url
        )

    def _default_verify(self, context: RuntimeContext, receipt: Path, expected_url: str) -> Probe:
        verifier_path = context.repo_root / "scripts/verify_agent_qa_receipt.py"
        source, error = pinned_verifier_source(verifier_path, VERIFIER_SHA256)
        if error:
            detail = "normal NOT READY: verifier_hash_mismatch" if error == "verifier_hash_mismatch" else "normal verifier unavailable"
            return Probe(False, detail)
        command = (
            str(context.repo_root / ".venv-agent/bin/python"),
            "-c", source.decode("utf-8"),
            "--require-mode", "normal", str(receipt),
        )
        try:
            result = context.run(command, env={"LIVEKIT_URL": expected_url}, timeout=20)
        except (OSError, subprocess.SubprocessError):
            return Probe(False, "normal verifier unavailable")
        return _verifier_result(result)

    def probe(self, context: RuntimeContext) -> Probe:
        if context.qa_mode:
            return Probe(False, "normal NOT READY: QA mode requested")
        external = self._external_path(context)
        if (
            not self._paths_distinct(context, external)
            or self._selected_receipt is not None
            and not self._paths_distinct(context, self._selected_receipt)
        ):
            return Probe(False, "normal NOT READY: normal and QA receipt paths match")
        try:
            expected_url = self._expected_url(context)
        except Exception as error:
            return Probe(False, f"normal NOT READY: {getattr(error, 'code', 'URL resolution failed')}")
        candidates = [self._selected_receipt] if self._selected_receipt else [external, self._owned_path(context)]
        reason = "receipt missing"
        for receipt in dict.fromkeys(path for path in candidates if path is not None and path.is_file()):
            verified = self._verifier(context, receipt, expected_url)
            if not verified.healthy:
                reason = verified.detail
                continue
            processes = _agent_processes(context)
            pid = _receipt_pid(receipt)
            if processes is None:
                return Probe(False, "normal NOT READY: process scan unavailable")
            if pid is None or processes != {pid: True}:
                return Probe(False, "normal NOT READY: exact room process conflict")
            owned_pid = self._owned_pid()
            if owned_pid is not None and pid != owned_pid:
                return Probe(False, "normal NOT READY: receipt PID mismatch")
            self._selected_receipt = receipt
            return Probe(True, verified.detail)
        return Probe(False, f"normal NOT READY: {reason}")

    def _owned_pid(self) -> int | None:
        children = {} if self._process is None else self._process._children
        return next(iter(children)) if len(children) == 1 else None

    def _config(self, context: RuntimeContext) -> dict[str, str]:
        try:
            database_result = context.run(
                ("supabase", "status", "-o", "json", "--workdir", str(context.repo_root)), timeout=5,
            )
            secret_result = context.run((*KUBECTL, "get", "secret/livekit-keys", "-o", "json"), timeout=5)
            database = json.loads(database_result.stdout) if database_result.returncode == 0 else {}
            data = json.loads(secret_result.stdout)["data"] if secret_result.returncode == 0 else {}
            values = {
                "DATABASE_URL": database.get("DB_URL", ""),
                "LIVEKIT_API_KEY": base64.b64decode(data["LIVEKIT_API_KEY"], validate=True).decode(),
                "LIVEKIT_API_SECRET": base64.b64decode(data["LIVEKIT_API_SECRET"], validate=True).decode(),
            }
        except (OSError, subprocess.SubprocessError, KeyError, TypeError, ValueError,
                UnicodeError, binascii.Error, json.JSONDecodeError):
            values = {}
        missing = [name.lower() for name in ("DATABASE_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET")
                   if not isinstance(values.get(name), str) or not values[name]]
        if missing:
            raise RuntimeError(f"normal NOT READY: configuration missing ({','.join(missing)})")
        return values

    def start(self, context: RuntimeContext) -> Identity:
        if context.qa_mode:
            raise RuntimeError("normal NOT READY: QA mode requested")
        if (
            not self._paths_distinct(context, self._external_path(context))
            or not self._paths_distinct(context, self._owned_path(context))
        ):
            raise RuntimeError("normal NOT READY: normal and QA receipt paths match")
        processes = _agent_processes(context)
        if processes is None:
            raise RuntimeError("normal NOT READY: process scan unavailable")
        if processes:
            raise RuntimeError("normal NOT READY: exact room process conflict")
        expected_url = self._expected_url(context)
        config = self._config(context)
        context.state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        receipt, log = self._owned_path(context), context.state_dir / "room-agent.log"
        receipt.unlink(missing_ok=True)
        log.unlink(missing_ok=True)
        self._selected_receipt = receipt
        env = {
            "LIVEKIT_AGENT_NAME": "", **config, "LIVEKIT_URL": expected_url,
            "AGENT_NORMAL_RECEIPT_FILE": str(receipt), "AGENT_LOG_FILE": str(log),
        }
        if "WORKER_LOAD_THRESHOLD" in os.environ:
            env["WORKER_LOAD_THRESHOLD"] = os.environ["WORKER_LOAD_THRESHOLD"]
        if "VOICE_STT_PORT" in os.environ:
            env["STT_URL"] = f"http://127.0.0.1:{int(os.environ['VOICE_STT_PORT'])}/inference"
        self._process = ProcessService(
            self.name,
            (str(context.repo_root / ".venv-agent/bin/python"), "agent/main.py", "start"),
            self.probe, cwd=context.repo_root, env=env, startup_timeout=30,
        )
        process = self._process.start(context)
        return {"process": process, "receipt": str(receipt)}

    def owns(self, context: RuntimeContext, identity: Identity) -> bool:
        process = identity.get("process")
        checker = self._process or ProcessService(self.name, (), self.probe)
        return (
            identity.get("receipt") == str(self._owned_path(context))
            and isinstance(process, dict) and checker.owns(context, process)
        )

    def stop(self, context: RuntimeContext, identity: Identity) -> None:
        if not self.owns(context, identity):
            raise RuntimeError("normal agent ownership changed; refusing cleanup")
        (self._process or ProcessService(self.name, (), self.probe)).stop(context, identity["process"])
        self._owned_path(context).unlink(missing_ok=True)
        (context.state_dir / "room-agent.log").unlink(missing_ok=True)
