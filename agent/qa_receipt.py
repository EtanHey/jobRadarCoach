import asyncio
import json
import logging
import math
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Awaitable, Callable
from urllib.parse import urlsplit


SCHEMA_VERSION = 2
DEFAULT_QA_RECEIPT_PATH = Path("docs.local/voice-qa-agent-receipt.json")
DEFAULT_NORMAL_RECEIPT_PATH = Path("docs.local/voice-normal-agent-receipt.json")
ROOM_COMMANDS = frozenset({"dev", "start"})
NORMAL_MODE_ENV_VALUES = frozenset({None, "", "0"})
QA_MODE_ENV_VALUES = frozenset({"1", "true", "yes", "on"})
_logger = logging.getLogger(__name__)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _process_start_time(pid: int) -> dict[str, str]:
    proc_stat = Path(f"/proc/{pid}/stat")
    boot_id = Path("/proc/sys/kernel/random/boot_id")
    if proc_stat.is_file() and boot_id.is_file():
        fields = proc_stat.read_text().split()
        return {
            "source": "linux_boot_id_and_start_ticks",
            "value": f"{boot_id.read_text().strip()}:{fields[21]}",
        }

    result = subprocess.run(
        ["ps", "-o", "lstart=", "-p", str(pid)],
        check=True,
        capture_output=True,
        text=True,
        timeout=2,
    )
    value = " ".join(result.stdout.split())
    if not value:
        raise RuntimeError("process start time was unavailable")
    return {"source": "ps_lstart", "value": value}


def _command_mode(argv: list[str]) -> str:
    return argv[1] if len(argv) > 1 else ""


def _host_load_per_cpu() -> float:
    cpu_count = os.cpu_count() or 1
    return os.getloadavg()[0] / cpu_count


def _safe_server_url(value: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"ws", "wss"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("LiveKit server URL is unsafe for the agent receipt")
    return value


class QaStartupReceipt:
    def __init__(self) -> None:
        self.voice_qa_mode_env = os.environ.get("VOICE_QA_MODE")
        normalized_qa_mode = (self.voice_qa_mode_env or "").strip().casefold()
        self.mode = "qa" if normalized_qa_mode in QA_MODE_ENV_VALUES else "normal"
        qa_path = Path(
            os.environ.get("VOICE_QA_RECEIPT_FILE", DEFAULT_QA_RECEIPT_PATH)
        )
        normal_path = Path(
            os.environ.get("AGENT_NORMAL_RECEIPT_FILE", DEFAULT_NORMAL_RECEIPT_PATH)
        )
        if qa_path.resolve() == normal_path.resolve():
            raise RuntimeError("QA and normal agent receipt paths must be different")
        self.path = qa_path if self.mode == "qa" else normal_path
        self.pid = os.getpid()
        self.start_time = _process_start_time(self.pid)
        self.command_mode = _command_mode(sys.argv)
        self.agent_name_env = os.environ.get("LIVEKIT_AGENT_NAME", "")
        self.worker_load_threshold = float(
            os.environ.get("WORKER_LOAD_THRESHOLD", "0.75")
        )
        self.host_load_at_startup = _host_load_per_cpu()
        if (
            not math.isfinite(self.worker_load_threshold)
            or self.worker_load_threshold <= 0
        ):
            raise ValueError("WORKER_LOAD_THRESHOLD must be a positive finite number")
        if not math.isfinite(self.host_load_at_startup) or self.host_load_at_startup < 0:
            raise RuntimeError("host load at startup is unavailable")
        self._last_payload: dict[str, object] | None = None

        reason = (
            None
            if self.command_mode in ROOM_COMMANDS
            else "console_or_non_room_mode"
        )
        self._write(
            self._base_payload(
                status="starting" if reason is None else "not_ready",
                reason=reason,
            )
        )

    def _base_payload(self, *, status: str, reason: str | None) -> dict[str, object]:
        return {
            "schema_version": SCHEMA_VERSION,
            "mode": self.mode,
            "worker_load_threshold": self.worker_load_threshold,
            "host_load_at_startup": self.host_load_at_startup,
            "status": status,
            "process": {"pid": self.pid, "start_time": self.start_time},
            "startup": {
                "voice_qa_mode": self.voice_qa_mode_env,
                "command_mode": self.command_mode,
                "room_mode": self.command_mode in ROOM_COMMANDS,
                "livekit_agent_name": self.agent_name_env,
            },
            "registration": None,
            "database": None,
            "reason": reason,
            "written_at": _utc_now(),
        }

    def _write(self, payload: dict[str, object]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f".{self.path.name}.{self.pid}.tmp")
        encoded = (
            json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        )
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        finally:
            if temporary.exists():
                temporary.unlink()
        self._last_payload = payload

    def bind_registration(
        self,
        *,
        server,
        owner_state_fingerprint: Callable[[], Awaitable[dict[str, object]]],
    ) -> None:
        @server.on("worker_registered")
        def registered(worker_id: str, _server_info: object) -> None:
            asyncio.create_task(
                self._write_ready(
                    worker_id=worker_id,
                    server_url=server._ws_url,
                    effective_agent_name=server._agent_name,
                    owner_state_fingerprint=owner_state_fingerprint,
                )
            )

    async def _write_ready(
        self,
        *,
        worker_id: str,
        server_url: str,
        effective_agent_name: str,
        owner_state_fingerprint: Callable[[], Awaitable[dict[str, object]]],
    ) -> None:
        try:
            server_url = _safe_server_url(server_url)
            automatic_registration = (
                self.agent_name_env == "" and effective_agent_name == ""
            )
            valid_mode_environment = (
                self.voice_qa_mode_env == "1"
                if self.mode == "qa"
                else self.voice_qa_mode_env in NORMAL_MODE_ENV_VALUES
            )
            ready = (
                self.command_mode in ROOM_COMMANDS
                and automatic_registration
                and bool(worker_id)
                and bool(server_url)
                and valid_mode_environment
                and math.isfinite(self.worker_load_threshold)
                and self.worker_load_threshold > 0
                and math.isfinite(self.host_load_at_startup)
            )
            owner_state: dict[str, object] | None = None
            transaction_read_only: bool | None = None
            if self.mode == "qa":
                owner_state = await owner_state_fingerprint()
                transaction_read_only = (
                    owner_state["database_transaction_read_only"] is True
                )
                ready = ready and transaction_read_only
            reason = None if ready else "startup_gate_not_satisfied"
            payload = self._base_payload(
                status="ready" if ready else "not_ready",
                reason=reason,
            )
            payload["registration"] = {
                "server_url": server_url,
                "worker_id": worker_id,
                "automatic": automatic_registration,
                "effective_agent_name": effective_agent_name,
            }
            if owner_state is not None:
                payload["database"] = {
                    "transaction_read_only": transaction_read_only,
                    "owner_tables": {
                        name: owner_state[name]
                        for name in ("posting_status", "profile", "active_mic")
                    },
                }
            payload["written_at"] = _utc_now()
            self._write(payload)
            _logger.log(
                logging.INFO if ready else logging.ERROR,
                "voice agent startup receipt written",
                extra={
                    "receipt_path": str(self.path),
                    "receipt_status": payload["status"],
                    "worker_id": worker_id,
                    "server_url": server_url,
                    "mode": self.mode,
                    "worker_load_threshold": self.worker_load_threshold,
                    "host_load_at_startup": self.host_load_at_startup,
                    "transaction_read_only": transaction_read_only,
                },
            )
        except Exception as exc:
            payload = self._base_payload(
                status="not_ready",
                reason="receipt_generation_failed",
            )
            payload["error_type"] = type(exc).__name__
            self._write(payload)
            _logger.exception(
                "voice agent startup receipt failed",
                extra={"receipt_path": str(self.path), "receipt_status": "not_ready"},
            )

    def invalidate(self, reason: str = "process_exited") -> None:
        payload = dict(
            self._last_payload or self._base_payload(status="stale", reason=reason)
        )
        payload["status"] = "stale"
        payload["reason"] = reason
        payload["written_at"] = _utc_now()
        self._write(payload)
        _logger.info(
            "voice agent startup receipt invalidated",
            extra={"receipt_path": str(self.path), "receipt_status": "stale"},
        )
