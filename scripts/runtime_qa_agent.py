"""Ownership-safe LiveKit room worker for ``jrc run --qa``."""

from __future__ import annotations

import base64
import binascii
import json
from pathlib import Path
import shlex
import subprocess
from typing import Callable

from scripts.runtime_process import Identity, Probe, ProcessService, RuntimeContext
from scripts.runtime_qa_config import resolve_qa_urls


KUBECTL = ("kubectl", "--context", "orbstack", "-n", "job-radar-coach")


def _agent_processes(context: RuntimeContext) -> dict[int, str | None] | None:
    try:
        result = context.run(("ps", "-axo", "pid=,command="), timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode:
        return None
    found: dict[int, str | None] = {}
    expected_paths = {Path("agent/main.py"), context.repo_root / "agent/main.py"}
    for line in result.stdout.splitlines():
        pid_text, _, command = line.strip().partition(" ")
        try:
            parts = shlex.split(command)
        except ValueError:
            parts = command.split()
        if not pid_text.isdigit() or not any(Path(item) in expected_paths for item in parts):
            continue
        valid = (
            len(parts) == 3
            and Path(parts[0]).name.startswith("python")
            and Path(parts[1]) in expected_paths
            and parts[2] in {"dev", "start"}
        )
        found[int(pid_text)] = parts[2] if valid else None
    return found


def _receipt_pid(path: Path) -> int | None:
    try:
        pid = json.loads(path.read_text())["process"]["pid"]
    except (OSError, KeyError, TypeError, json.JSONDecodeError):
        return None
    return pid if isinstance(pid, int) and not isinstance(pid, bool) and pid > 0 else None


def _not_ready(result: subprocess.CompletedProcess[str] | None) -> str:
    if result is None:
        return "verifier_unavailable"
    fields = result.stderr.split(maxsplit=2)
    if len(fields) >= 2 and fields[0] == "NOT_READY" and fields[1].replace("_", "").isalnum():
        return fields[1]
    return "verifier_output_invalid" if result.returncode == 0 else "verifier_failed"


class QaAgentService:
    """Borrows one verified QA worker or owns one exact room-worker process."""

    name = "qa-agent"

    def __init__(
        self,
        receipt_path: Path | None = None,
        url_provider: Callable[[RuntimeContext], str] | None = None,
    ) -> None:
        self._external_receipt = receipt_path
        self._url_provider = url_provider
        self._selected_receipt: Path | None = None
        self._process: ProcessService | None = None

    def _external_path(self, context: RuntimeContext) -> Path:
        return self._external_receipt or context.repo_root / "docs.local/voice-qa-agent-receipt.json"

    @staticmethod
    def _owned_path(context: RuntimeContext) -> Path:
        return context.state_dir / "qa-agent-receipt.json"

    def receipt_path(self, context: RuntimeContext) -> Path:
        return self._selected_receipt or self._external_path(context)

    def _expected_url(self, context: RuntimeContext) -> str:
        return self._url_provider(context) if self._url_provider else (
            resolve_qa_urls(context).expected_livekit_url
        )

    def _verify(self, context: RuntimeContext, receipt: Path, expected_url: str) -> tuple[str | None, str]:
        verifier = context.repo_root / "scripts/verify_agent_qa_receipt.py"
        command = (str(context.repo_root / ".venv-agent/bin/python"), str(verifier), str(receipt))
        try:
            result = context.run(command, env={"LIVEKIT_URL": expected_url}, timeout=20)
        except (OSError, subprocess.SubprocessError):
            return None, "verifier_unavailable"
        try:
            value = json.loads(result.stdout)
            worker = value["worker_id"]
            exact = result.stdout == json.dumps(
                {"status": "READY", "worker_id": worker}, separators=(",", ":"),
            ) + "\n"
            if (
                result.returncode == 0 and result.stderr == "" and exact
                and isinstance(worker, str) and worker
            ):
                return worker, ""
        except (KeyError, TypeError, json.JSONDecodeError):
            pass
        return None, _not_ready(result)

    def _owned_pid(self) -> int | None:
        children = {} if self._process is None else self._process._children
        return next(iter(children)) if len(children) == 1 else None

    def probe(self, context: RuntimeContext) -> Probe:
        try:
            expected_url = self._expected_url(context)
        except Exception as error:
            return Probe(False, f"QA NOT READY: {getattr(error, 'code', 'url_resolution_failed')}")
        candidates = [self._selected_receipt] if self._selected_receipt else [
            self._external_path(context), self._owned_path(context),
        ]
        reason = "receipt_missing"
        for receipt in dict.fromkeys(path for path in candidates if path is not None and path.is_file()):
            worker, reason = self._verify(context, receipt, expected_url)
            if worker is None:
                continue
            processes = _agent_processes(context)
            pid = _receipt_pid(receipt)
            if processes is None:
                return Probe(False, "QA NOT READY: agent_process_scan_unavailable")
            if pid is None or processes != {pid: processes.get(pid)} or processes.get(pid) not in {"dev", "start"}:
                return Probe(False, "QA NOT READY: agent_process_conflict")
            owned_pid = self._owned_pid()
            if owned_pid is not None and pid != owned_pid:
                return Probe(False, "QA NOT READY: receipt_pid_mismatch")
            self._selected_receipt = receipt
            return Probe(True, f"verified QA worker {worker}")
        return Probe(False, f"QA NOT READY: {reason}")

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
            raise RuntimeError(f"QA NOT READY: configuration_missing ({','.join(missing)})")
        return values

    def start(self, context: RuntimeContext) -> Identity:
        if not context.qa_mode:
            raise RuntimeError("QA NOT READY: qa_mode_not_requested")
        processes = _agent_processes(context)
        if processes is None:
            raise RuntimeError("QA NOT READY: agent_process_scan_unavailable")
        if processes:
            raise RuntimeError("QA NOT READY: agent_process_conflict")
        expected_url = self._expected_url(context)
        config = self._config(context)
        context.state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        receipt, log = self._owned_path(context), context.state_dir / "qa-agent.log"
        receipt.unlink(missing_ok=True)
        log.unlink(missing_ok=True)
        self._selected_receipt = receipt
        env = {
            "VOICE_QA_MODE": "1", "LIVEKIT_AGENT_NAME": "", **config,
            "LIVEKIT_URL": expected_url, "VOICE_QA_RECEIPT_FILE": str(receipt),
            "AGENT_LOG_FILE": str(log),
        }
        self._process = ProcessService(
            self.name,
            (str(context.repo_root / ".venv-agent/bin/python"), "agent/main.py", "dev"),
            self.probe, cwd=context.repo_root, env=env, startup_timeout=30,
        )
        process = self._process.start(context)
        return {"process": process, "receipt": str(receipt)}

    def owns(self, context: RuntimeContext, identity: Identity) -> bool:
        process = identity.get("process")
        expected = str(self._owned_path(context))
        checker = self._process or ProcessService(self.name, (), self.probe)
        return identity.get("receipt") == expected and isinstance(process, dict) and checker.owns(context, process)

    def stop(self, context: RuntimeContext, identity: Identity) -> None:
        if not self.owns(context, identity):
            raise RuntimeError("QA agent ownership changed; refusing cleanup")
        process = identity["process"]
        (self._process or ProcessService(self.name, (), self.probe)).stop(context, process)
        self._owned_path(context).unlink(missing_ok=True)
        (context.state_dir / "qa-agent.log").unlink(missing_ok=True)
