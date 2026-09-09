"""Identity-fenced lifecycle adapters for local voice resources."""

from __future__ import annotations

import json
import re
import subprocess
import time
from typing import Any, Sequence

from scripts.runtime_control import PartialStartError
from scripts.runtime_process import Identity, Probe, RuntimeContext


KOKORO_CONTAINER_NAME = "kokoro"
KOKORO_IMAGE = "ghcr.io/remsky/kokoro-fastapi-cpu:latest"
KOKORO_PORT_BINDINGS = {"8880/tcp": [{"HostIp": "", "HostPort": "8881"}]}
POST_START_INSPECT_ATTEMPTS = 3
POST_START_INSPECT_INTERVAL = 0.1
UNCONFIRMED_AFTER_START = "unconfirmed_after_start"
_CONTAINER_ID = re.compile(r"[0-9a-f]{64}")
_IMAGE_ID = re.compile(r"sha256:[0-9a-f]{64}")


class KokoroContainerService:
    """Own start/stop state for an approved, preinstalled Kokoro container."""

    name = "kokoro"
    lifecycle_owned = True

    def __init__(self, *, startup_timeout: float = 60, readiness_interval: float = 0.5) -> None:
        self.startup_timeout = startup_timeout
        self.readiness_interval = readiness_interval

    @staticmethod
    def _result(context: RuntimeContext, command: Sequence[str], *, timeout: float):
        try:
            return context.run(command, timeout=timeout)
        except (OSError, subprocess.TimeoutExpired):
            return None

    def _inspect(self, context: RuntimeContext, reference: str) -> dict[str, Any] | None:
        result = self._result(
            context, ("docker", "container", "inspect", reference), timeout=5,
        )
        if result is None or result.returncode:
            return None
        try:
            value = json.loads(result.stdout)
        except (json.JSONDecodeError, UnicodeError):
            return None
        if not isinstance(value, list) or len(value) != 1 or not isinstance(value[0], dict):
            return None
        return value[0]

    @staticmethod
    def _approved(snapshot: dict[str, Any]) -> bool:
        config = snapshot.get("Config", {})
        host = snapshot.get("HostConfig", {})
        return (
            snapshot.get("Name") == f"/{KOKORO_CONTAINER_NAME}"
            and _CONTAINER_ID.fullmatch(str(snapshot.get("Id", ""))) is not None
            and _IMAGE_ID.fullmatch(str(snapshot.get("Image", ""))) is not None
            and config.get("Image") == KOKORO_IMAGE
            and config.get("Entrypoint") is None
            and config.get("Cmd") == ["./entrypoint.sh"]
            and host.get("PortBindings") == KOKORO_PORT_BINDINGS
            and host.get("RestartPolicy") == {"Name": "no", "MaximumRetryCount": 0}
            and host.get("AutoRemove") is False
            and host.get("NetworkMode") == "bridge"
            and snapshot.get("Mounts") == []
        )

    @staticmethod
    def _running(snapshot: dict[str, Any]) -> bool:
        state = snapshot.get("State", {})
        return state.get("Running") is True and state.get("Status") == "running"

    @staticmethod
    def _identity(snapshot: dict[str, Any]) -> Identity | None:
        state = snapshot.get("State", {})
        values = {
            "container_id": snapshot.get("Id"),
            "image_id": snapshot.get("Image"),
            "started_at": state.get("StartedAt"),
        }
        return values if all(isinstance(value, str) and value for value in values.values()) else None

    def _matches_identity(self, snapshot: dict[str, Any], identity: Identity) -> bool:
        if identity.get("ownership_status") == UNCONFIRMED_AFTER_START:
            return False
        current = self._identity(snapshot)
        return self._approved(snapshot) and current is not None and current == {
            "container_id": identity.get("container_id"),
            "image_id": identity.get("image_id"),
            "started_at": identity.get("started_at"),
        }

    @staticmethod
    def _unconfirmed_identity(snapshot: dict[str, Any]) -> Identity:
        return {
            "container_id": snapshot["Id"],
            "image_id": snapshot["Image"],
            "ownership_status": UNCONFIRMED_AFTER_START,
        }

    def _inspect_after_start(
        self, context: RuntimeContext, reference: str,
    ) -> dict[str, Any] | None:
        for attempt in range(POST_START_INSPECT_ATTEMPTS):
            current = self._inspect(context, reference)
            if current is not None and self._identity(current) is not None:
                return current
            if attempt + 1 < POST_START_INSPECT_ATTEMPTS:
                time.sleep(POST_START_INSPECT_INTERVAL)
        return None

    def _health(self, context: RuntimeContext) -> bool:
        result = self._result(
            context,
            (
                "curl", "-fsS", "-o", "/dev/null", "--max-time", "10",
                "http://127.0.0.1:8881/v1/models",
            ),
            timeout=11,
        )
        return result is not None and result.returncode == 0

    def probe(self, context: RuntimeContext) -> Probe:
        snapshot = self._inspect(context, KOKORO_CONTAINER_NAME)
        if snapshot is None or not self._approved(snapshot):
            return Probe(False, "approved Kokoro container is missing or unidentified")
        if not self._running(snapshot):
            return Probe(False, "approved Kokoro container is stopped")
        healthy = self._health(context)
        return Probe(
            healthy,
            "approved Kokoro container healthy" if healthy
            else "approved Kokoro container running; health endpoint unavailable",
        )

    def start(self, context: RuntimeContext) -> Identity:
        before = self._inspect(context, KOKORO_CONTAINER_NAME)
        if before is None or not self._approved(before):
            raise RuntimeError("approved Kokoro container is missing or does not match runtime shape")
        if self._running(before):
            identity = self._identity(before)
            if identity is None or not self._health(context):
                raise RuntimeError("approved Kokoro container is running but not healthy")
            return identity
        if before.get("State", {}).get("Status") not in {"created", "exited"}:
            raise RuntimeError("approved Kokoro container is not in a startable state")
        if context.stop_requested():
            raise InterruptedError("stop requested before starting Kokoro")

        result = self._result(
            context, ("docker", "container", "start", str(before["Id"])), timeout=15,
        )
        current = self._inspect_after_start(context, str(before["Id"]))
        if current is None:
            raise PartialStartError(
                "Kokoro post-start identity could not be confirmed",
                self._unconfirmed_identity(before),
            )
        identity = self._identity(current)
        if identity is None:
            raise PartialStartError(
                "Kokoro post-start identity could not be confirmed",
                self._unconfirmed_identity(before),
            )
        if result is None or result.returncode or not self._running(current):
            raise PartialStartError("Kokoro container did not start cleanly", identity)
        if not self._matches_identity(current, identity):
            raise PartialStartError("Kokoro identity changed during startup", identity)

        deadline = time.monotonic() + self.startup_timeout
        while time.monotonic() < deadline:
            current = self._inspect(context, str(identity["container_id"]))
            if current is None or not self._matches_identity(current, identity):
                raise PartialStartError("Kokoro identity changed during readiness", identity)
            if not self._running(current):
                raise PartialStartError("Kokoro container stopped during readiness", identity)
            if self._health(context):
                return identity
            if context.stop_requested():
                raise PartialStartError("Kokoro startup interrupted", identity)
            time.sleep(self.readiness_interval)
        raise PartialStartError("Kokoro startup health check timed out", identity)

    def owns(self, context: RuntimeContext, identity: Identity) -> bool:
        if identity.get("ownership_status") == UNCONFIRMED_AFTER_START:
            return False
        reference = identity.get("container_id")
        if not isinstance(reference, str) or not reference:
            return False
        snapshot = self._inspect(context, reference)
        return snapshot is not None and self._matches_identity(snapshot, identity)

    def is_running(self, context: RuntimeContext, identity: Identity) -> bool | None:
        if identity.get("ownership_status") == UNCONFIRMED_AFTER_START:
            return None
        reference = identity.get("container_id")
        if not isinstance(reference, str) or not reference:
            return None
        snapshot = self._inspect(context, reference)
        if snapshot is None:
            return None
        return self._matches_identity(snapshot, identity) and self._running(snapshot)

    def stop(self, context: RuntimeContext, identity: Identity) -> None:
        if identity.get("ownership_status") == UNCONFIRMED_AFTER_START:
            raise RuntimeError(
                "Kokoro post-start identity was unconfirmed; refusing cleanup"
            )
        reference = identity.get("container_id")
        if not isinstance(reference, str) or not reference:
            raise RuntimeError("Kokoro container identity is invalid")
        before = self._inspect(context, reference)
        if before is None or not self._matches_identity(before, identity):
            raise RuntimeError("Kokoro container identity changed; refusing cleanup")
        if not self._running(before):
            return
        result = self._result(
            context, ("docker", "container", "stop", "--time", "10", reference),
            timeout=15,
        )
        after = self._inspect(context, reference)
        if after is not None and self._matches_identity(after, identity) and not self._running(after):
            return
        if result is None or result.returncode:
            raise RuntimeError("failed to stop owned Kokoro container")
        raise RuntimeError("owned Kokoro container still running or identity changed after stop")
