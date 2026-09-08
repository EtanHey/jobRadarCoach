"""Fail-closed owned runtime for browser/phone voice QA."""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import uuid
from typing import Any, Callable, Sequence

from scripts.runtime_control import PartialStartError, Service
from scripts.runtime_process import ProcessService, Probe, RuntimeContext, same_process
from scripts.runtime_qa_config import resolve_qa_urls


KUBECTL = ("kubectl", "--context", "orbstack", "-n", "job-radar-coach")
_MAPPING_UNKNOWN = "<status-unavailable>"


def _not_ready(result: subprocess.CompletedProcess[str] | None) -> str:
    if result is None:
        return "verifier_unavailable"
    for line in result.stderr.splitlines():
        fields = line.split()
        if len(fields) >= 2 and fields[0] == "NOT_READY":
            return fields[1]
    return "verifier_output_invalid" if result.returncode == 0 else "verifier_failed"


def _secret(context: RuntimeContext, name: str) -> dict[str, str]:
    result = context.run((*KUBECTL, "get", f"secret/{name}", "-o", "json"), timeout=5)
    if result.returncode:
        return {}
    try:
        data = json.loads(result.stdout)["data"]
        return {key: base64.b64decode(value, validate=True).decode() for key, value in data.items()}
    except (KeyError, TypeError, ValueError, UnicodeError, json.JSONDecodeError):
        return {}


def _json(context: RuntimeContext, command: Sequence[str]) -> dict[str, Any] | None:
    try:
        result = context.run(command, timeout=5)
        value = json.loads(result.stdout) if result.returncode == 0 else None
        return value if isinstance(value, dict) else None
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        return None


class QaRuntimeService:
    """Owns one proxy process and, for phone mode, one exact Serve mapping."""

    name = "qa-runtime"

    def __init__(self, receipt_provider: Callable[[RuntimeContext], Path] | None = None) -> None:
        self._process: ProcessService | None = None
        self._session_id: str | None = None
        self._receipt_provider = receipt_provider

    @staticmethod
    def _marker_path(context: RuntimeContext) -> Path:
        return context.state_dir / "qa-runtime.json"

    def _marker(self, context: RuntimeContext) -> dict[str, Any] | None:
        try:
            value = json.loads(self._marker_path(context).read_text())
            return value if isinstance(value, dict) else None
        except (OSError, json.JSONDecodeError):
            return None

    def _active_identity(self, context: RuntimeContext) -> dict[str, Any] | None:
        try:
            state = json.loads((context.state_dir / "state.json").read_text())
            owner = state["supervisor"]
            entry = next(item for item in state["services"] if item.get("name") == self.name)
            identity = dict(entry["identity"])
            identity["_supervisor_pid"] = owner.get("pid")
            return identity if same_process(owner) else None
        except (OSError, KeyError, StopIteration, TypeError, ValueError, json.JSONDecodeError):
            return None

    def probe(self, context: RuntimeContext) -> Probe:
        marker = self._marker(context) or {}
        identity = self._active_identity(context)
        current_start = (
            self._session_id is not None
            and marker.get("session_id") == self._session_id
            and marker.get("supervisor_pid") == os.getpid()
        )
        active = (
            isinstance(identity, dict) and isinstance(identity.get("process"), dict)
            and marker.get("session_id") == identity.get("session_id")
            and marker.get("worker_id") == identity.get("worker_id")
            and marker.get("supervisor_pid") == identity.get("_supervisor_pid")
        )
        process_ok = current_start or (active and same_process(identity["process"]))
        mapping = identity.get("mapping") if active else None
        mapping_ok = not isinstance(mapping, dict) or self._mapping_target(context, mapping) == mapping.get("target")
        ready = marker.get("status") == "READY" and process_ok and mapping_ok
        reason = "tailnet_mapping_changed" if not mapping_ok else (marker.get("reason") or "receipt_unverified")
        detail = marker.get("qa_url") if ready else f"QA NOT READY: {reason}"
        return Probe(ready, str(detail))

    def _verify(self, context: RuntimeContext, verifier: Path, receipt: Path,
                expected_server: str) -> tuple[str | None, str]:
        if not verifier.is_file():
            return None, "verifier_missing"
        try:
            result = context.run(
                (sys.executable, str(verifier), str(receipt)),
                env={"LIVEKIT_URL": expected_server}, timeout=20,
            )
        except (OSError, subprocess.SubprocessError):
            return None, "verifier_unavailable"
        try:
            value = json.loads(result.stdout)
            exact = set(value) == {"status", "worker_id"}
            worker = value["worker_id"] if exact and value["status"] == "READY" else None
            if result.returncode == 0 and isinstance(worker, str) and worker:
                return worker, ""
        except (KeyError, TypeError, json.JSONDecodeError):
            pass
        return None, _not_ready(result)

    def _config(self, context: RuntimeContext) -> dict[str, str]:
        urls = resolve_qa_urls(context)
        livekit = {}
        if not (os.environ.get("LIVEKIT_API_KEY") and os.environ.get("LIVEKIT_API_SECRET")):
            livekit = _secret(context, "livekit-keys")
        ui = {} if os.environ.get("UI_ORIGIN") else _secret(context, "ui-runtime")
        values = {
            "LIVEKIT_API_KEY": os.environ.get("LIVEKIT_API_KEY") or livekit.get("LIVEKIT_API_KEY", ""),
            "LIVEKIT_API_SECRET": os.environ.get("LIVEKIT_API_SECRET") or livekit.get("LIVEKIT_API_SECRET", ""),
            "QA_UPSTREAM": os.environ.get("VOICE_QA_UPSTREAM", "http://127.0.0.1:3410"),
            "QA_UPSTREAM_ORIGIN": os.environ.get("UI_ORIGIN") or ui.get("UI_ORIGIN", ""),
            "QA_EXPECTED_LIVEKIT_URL": urls.expected_livekit_url,
            "QA_PUBLIC_LIVEKIT_URL": urls.public_livekit_url,
        }
        missing = [key.lower() for key, value in values.items() if not value]
        if missing:
            raise RuntimeError(f"QA NOT READY: configuration_missing ({','.join(missing)})")
        return values

    @staticmethod
    def _free_loopback_port() -> int:
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            return int(listener.getsockname()[1])

    def _serve(self, context: RuntimeContext) -> tuple[dict[str, Any], str]:
        serve = _json(context, ("tailscale", "serve", "status", "--json"))
        status = _json(context, ("tailscale", "status", "--json"))
        try:
            dns = status["Self"]["DNSName"].rstrip(".")
            tcp, web = serve.get("TCP", {}), serve.get("Web", {})
            for port in range(8450, 8500):
                if str(port) not in tcp and f"{dns}:{port}" not in web:
                    return {"port": port, "dns": dns}, f"https://{dns}:{port}"
        except (AttributeError, KeyError, TypeError):
            pass
        raise RuntimeError("QA NOT READY: unused_tailnet_https_port_unavailable")

    def _mapping_target(self, context: RuntimeContext, mapping: dict[str, Any]) -> str | None:
        serve = _json(context, ("tailscale", "serve", "status", "--json"))
        if serve is None:
            return _MAPPING_UNKNOWN
        try:
            port, dns = str(mapping["port"]), mapping["dns"]
            entry = serve["TCP"].get(port)
            handlers = serve["Web"].get(f"{dns}:{port}", {}).get("Handlers", {})
            if entry is None and not handlers:
                return None
            if entry == {"HTTPS": True} and set(handlers) == {"/"}:
                return handlers["/"]["Proxy"]
        except (AttributeError, KeyError, TypeError):
            pass
        return "<occupied>"

    def _remove_mapping(self, context: RuntimeContext, mapping: dict[str, Any]) -> None:
        current = self._mapping_target(context, mapping)
        if current is None:
            return
        if current == _MAPPING_UNKNOWN:
            raise RuntimeError("QA tailnet mapping status unavailable; cleanup unconfirmed")
        if current != mapping["target"]:
            raise RuntimeError("QA tailnet mapping changed; refusing cleanup")
        command = ("tailscale", "serve", f"--https={mapping['port']}", "off")
        result = context.run(command, timeout=5)
        if result.returncode or self._mapping_target(context, mapping) is not None:
            raise RuntimeError("QA tailnet mapping cleanup unconfirmed")

    def start(self, context: RuntimeContext) -> dict[str, Any]:
        if not context.qa_mode:
            raise RuntimeError("QA NOT READY: qa_mode_not_requested")
        config = self._config(context)
        verifier = Path(os.environ.get(
            "VOICE_QA_VERIFIER_FILE", context.repo_root / "scripts/verify_agent_qa_receipt.py",
        ))
        receipt = self._receipt_provider(context) if self._receipt_provider else Path(os.environ.get(
            "VOICE_QA_RECEIPT_FILE", context.repo_root / "docs.local/voice-qa-agent-receipt.json",
        ))
        worker, reason = self._verify(context, verifier, receipt, config["QA_EXPECTED_LIVEKIT_URL"])
        if worker is None:
            raise RuntimeError(f"QA NOT READY: {reason}")
        self._session_id = str(uuid.uuid4())
        marker = self._marker_path(context)
        marker.unlink(missing_ok=True)
        proxy_port = self._free_loopback_port()
        phone = os.environ.get("VOICE_QA_PHONE") == "1"
        mapping, public_origin = self._serve(context) if phone else (None, "")
        env = {
            **config, "QA_SESSION_ID": self._session_id, "QA_EXPECTED_WORKER_ID": worker,
            "QA_VERIFIER_PATH": str(verifier), "QA_RECEIPT_PATH": str(receipt),
            "QA_RUNTIME_STATE_FILE": str(marker), "QA_PROXY_PORT": str(proxy_port),
            "QA_SUPERVISOR_PID": str(os.getpid()), "QA_PUBLIC_ORIGIN": public_origin,
        }
        for key in ("QA_PROXY_MODULE", "QA_VERIFY_INTERVAL_MS", "QA_PYTHON"):
            if key in os.environ:
                env[key] = os.environ[key]
        self._process = ProcessService(
            self.name, ("node", str(context.repo_root / "scripts/runtime_qa_proxy.mjs")),
            self.probe, env=env, startup_timeout=20,
        )
        process = self._process.start(context)
        identity: dict[str, Any] = {
            "session_id": self._session_id, "process": process,
            "receipt": str(receipt), "worker_id": worker,
        }
        if mapping is None:
            return identity
        mapping["target"] = f"http://127.0.0.1:{proxy_port}"
        command = ("tailscale", "serve", "--bg", f"--https={mapping['port']}", mapping["target"])
        try:
            current = self._mapping_target(context, mapping)
            if current == _MAPPING_UNKNOWN:
                raise RuntimeError("QA tailnet mapping status unavailable before startup")
            if current is not None:
                raise RuntimeError("QA tailnet port became occupied; refusing replacement")
            identity["mapping"] = mapping
            result = context.run(command, timeout=5)
            applied = self._mapping_target(context, mapping) == mapping["target"]
            if result.returncode or not applied:
                raise RuntimeError("QA tailnet mapping startup unconfirmed")
            return identity
        except BaseException as error:
            cleanup_error = None
            if "mapping" in identity:
                try:
                    self._remove_mapping(context, mapping)
                    identity.pop("mapping")
                except Exception as caught:
                    cleanup_error = caught
            try:
                self._process.stop(context, process)
            except Exception as caught:
                cleanup_error = cleanup_error or caught
            if cleanup_error:
                raise PartialStartError(f"{error}; rollback unconfirmed: {cleanup_error}", identity) from error
            raise

    def owns(self, context: RuntimeContext, identity: dict[str, Any]) -> bool:
        process = identity.get("process")
        if not isinstance(process, dict):
            return False
        checker = self._process or ProcessService(self.name, (), self.probe)
        return checker.owns(context, process)

    def stop(self, context: RuntimeContext, identity: dict[str, Any]) -> None:
        errors = []
        mapping = identity.get("mapping")
        if isinstance(mapping, dict):
            try:
                self._remove_mapping(context, mapping)
            except Exception as error:
                errors.append(str(error))
        process = identity["process"]
        try:
            (self._process or ProcessService(self.name, (), self.probe)).stop(context, process)
        except Exception as error:
            errors.append(str(error))
        marker = self._marker(context)
        if marker and marker.get("session_id") == identity.get("session_id") and not errors:
            self._marker_path(context).unlink(missing_ok=True)
        if errors:
            raise RuntimeError("; ".join(errors))


def build_qa_services(context: RuntimeContext) -> Sequence[Service]:
    if not context.qa_mode:
        raise RuntimeError("QA adapter requires --qa")
    return [QaRuntimeService()]
