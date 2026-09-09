"""Identity-fenced lifecycle adapter for the local LiveKit Deployment."""
from __future__ import annotations

import copy
import hashlib
import json
import re
import subprocess
import time
from typing import Any, Sequence

from scripts.runtime_control import PartialStartError
from scripts.runtime_process import Identity, Probe, RuntimeContext


KUBECTL = ("kubectl", "--context", "orbstack", "-n", "job-radar-coach")
DEPLOYMENT = "deployment/livekit"
_UID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


class LiveKitDeploymentService:
    name = "livekit"
    lifecycle_owned = True

    def __init__(self, *, startup_timeout: float = 60, readiness_interval: float = 0.5) -> None:
        self.startup_timeout = startup_timeout
        self.readiness_interval = readiness_interval

    @staticmethod
    def _result(context: RuntimeContext, command: Sequence[str], *, timeout: float = 5):
        try:
            return context.run(command, timeout=timeout)
        except (OSError, subprocess.TimeoutExpired):
            return None

    @staticmethod
    def _object(result: Any) -> dict[str, Any] | None:
        if result is None or result.returncode:
            return None
        try:
            value = json.loads(result.stdout)
        except (json.JSONDecodeError, UnicodeError):
            return None
        return value if isinstance(value, dict) else None

    def _get(self, context: RuntimeContext, resource: str) -> dict[str, Any] | None:
        return self._object(self._result(context, (*KUBECTL, "get", resource, "-o", "json")))

    def _deployment(self, context: RuntimeContext) -> dict[str, Any] | None:
        return self._get(context, DEPLOYMENT)

    @staticmethod
    def _approved(snapshot: dict[str, Any]) -> bool:
        metadata = snapshot.get("metadata", {})
        spec = snapshot.get("spec", {})
        template = spec.get("template", {})
        pod = template.get("spec", {})
        containers = pod.get("containers", [])
        if (
            snapshot.get("apiVersion") != "apps/v1"
            or snapshot.get("kind") != "Deployment"
            or metadata.get("name") != "livekit"
            or metadata.get("namespace") != "job-radar-coach"
            or _UID.fullmatch(str(metadata.get("uid", ""))) is None
            or spec.get("selector", {}).get("matchLabels") != {"app": "livekit"}
            or template.get("metadata", {}).get("labels") != {"app": "livekit"}
            or pod.get("enableServiceLinks") is not False
            or len(containers) != 1
        ):
            return False
        container = containers[0]
        env = {item.get("name"): item for item in container.get("env", [])}
        ports = {
            (item.get("containerPort"), item.get("protocol", "TCP"))
            for item in container.get("ports", [])
        }
        volumes = {item.get("name"): item for item in pod.get("volumes", [])}
        mounts = {item.get("name"): item for item in container.get("volumeMounts", [])}
        return (
            container.get("name") == "livekit"
            and container.get("image") == "livekit/livekit-server:latest"
            and container.get("args") == ["--config", "/etc/livekit/livekit.yaml"]
            and len(container.get("ports", [])) == 3 and ports == {(7880, "TCP"), (7881, "TCP"), (50000, "UDP")}
            and len(container.get("env", [])) == 4 and set(env) == {"NODE_IP", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET", "LIVEKIT_KEYS"}
            and env.get("NODE_IP", {}).get("valueFrom", {}).get("configMapKeyRef")
            == {"key": "node_ip", "name": "livekit-advertise"}
            and env.get("LIVEKIT_API_KEY", {}).get("valueFrom", {}).get("secretKeyRef")
            == {"key": "LIVEKIT_API_KEY", "name": "livekit-keys"}
            and env.get("LIVEKIT_API_SECRET", {}).get("valueFrom", {}).get("secretKeyRef")
            == {"key": "LIVEKIT_API_SECRET", "name": "livekit-keys"}
            and env.get("LIVEKIT_KEYS") == {
                "name": "LIVEKIT_KEYS", "value": "$(LIVEKIT_API_KEY): $(LIVEKIT_API_SECRET)",
            }
            and mounts.get("config", {}).get("mountPath") == "/etc/livekit"
            and len(container.get("volumeMounts", [])) == 1 and set(mounts) == {"config"}
            and volumes.get("config", {}).get("configMap", {}).get("name") == "livekit-config"
            and len(pod.get("volumes", [])) == 1 and set(volumes) == {"config"}
        )

    @staticmethod
    def _identity(snapshot: dict[str, Any]) -> Identity | None:
        metadata, spec = snapshot.get("metadata", {}), snapshot.get("spec", {})
        uid, generation, replicas = metadata.get("uid"), metadata.get("generation"), spec.get("replicas")
        if (
            _UID.fullmatch(str(uid or "")) is None
            or not isinstance(generation, int) or isinstance(generation, bool) or generation < 1
            or not isinstance(replicas, int) or isinstance(replicas, bool) or replicas < 0
        ):
            return None
        fingerprint = hashlib.sha256(
            json.dumps(spec, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        return {"deployment_uid": uid, "generation": generation, "spec_sha256": fingerprint, "replicas": replicas}

    def _matches_identity(self, snapshot: dict[str, Any], identity: Identity) -> bool:
        return self._approved(snapshot) and self._identity(snapshot) == {
            key: identity.get(key) for key in ("deployment_uid", "generation", "spec_sha256", "replicas")
        }

    @staticmethod
    def _ready(snapshot: dict[str, Any]) -> bool:
        metadata, spec, status = snapshot.get("metadata", {}), snapshot.get("spec", {}), snapshot.get("status", {})
        return (
            spec.get("replicas") == 1
            and status.get("observedGeneration") == metadata.get("generation")
            and all(status.get(key) == 1 for key in ("updatedReplicas", "readyReplicas", "availableReplicas"))
        )

    def _prerequisites(self, context: RuntimeContext) -> Probe:
        service = self._get(context, "service/livekit") or {}
        ports = {
            (item.get("port"), item.get("targetPort"), item.get("protocol", "TCP"))
            for item in service.get("spec", {}).get("ports", [])
        }
        if ports != {(7880, 7880, "TCP"), (7881, 7881, "TCP"), (50000, 50000, "UDP")}:
            return Probe(False, "service/livekit ports do not match the voice contract")
        config = self._get(context, "configmap/livekit-advertise") or {}
        tail_ip = self._result(context, ("tailscale", "ip", "-4"))
        expected = "" if tail_ip is None or tail_ip.returncode else tail_ip.stdout.strip()
        if not expected or config.get("data") != {"node_ip": expected}:
            return Probe(False, "livekit-advertise node_ip does not match Tailscale")
        return Probe(True, "LiveKit prerequisites ready")

    def probe(self, context: RuntimeContext) -> Probe:
        snapshot = self._deployment(context)
        if snapshot is None or not self._approved(snapshot) or self._identity(snapshot) is None:
            return Probe(False, "approved deployment/livekit is missing or unidentified")
        replicas = snapshot.get("spec", {}).get("replicas")
        if replicas == 0:
            return Probe(False, "approved deployment/livekit is scaled down")
        if replicas != 1 or not self._ready(snapshot):
            return Probe(False, "approved deployment/livekit is not ready")
        prerequisite = self._prerequisites(context)
        return Probe(prerequisite.healthy, "deployment/livekit ready" if prerequisite.healthy else prerequisite.detail)

    def _patch_replicas(self, context: RuntimeContext, before: dict[str, Any], target: int) -> dict[str, Any] | None:
        identity = self._identity(before)
        if identity is None:
            return None
        patch = [
            {"op": "test", "path": "/metadata/uid", "value": identity["deployment_uid"]},
            {"op": "test", "path": "/metadata/generation", "value": identity["generation"]},
            {"op": "test", "path": "/spec/replicas", "value": identity["replicas"]},
            {"op": "replace", "path": "/spec/replicas", "value": target},
        ]
        result = self._result(
            context,
            (*KUBECTL, "patch", DEPLOYMENT, "--type=json", "-p", json.dumps(patch), "-o", "json"),
            timeout=15,
        )
        return self._object(result)

    @staticmethod
    def _expected_transition(before: dict[str, Any], after: dict[str, Any], target: int) -> bool:
        expected_spec = copy.deepcopy(before.get("spec"))
        if not isinstance(expected_spec, dict):
            return False
        expected_spec["replicas"] = target
        return (
            after.get("metadata", {}).get("uid") == before.get("metadata", {}).get("uid")
            and after.get("metadata", {}).get("generation")
            == before.get("metadata", {}).get("generation") + 1
            and after.get("spec") == expected_spec
        )

    def _wait_ready(self, context: RuntimeContext, identity: Identity) -> None:
        deadline = time.monotonic() + self.startup_timeout
        while time.monotonic() < deadline:
            current = self._deployment(context)
            if current is None or not self._matches_identity(current, identity):
                raise RuntimeError("deployment/livekit identity changed during readiness")
            prerequisite = self._prerequisites(context)
            if self._ready(current) and prerequisite.healthy:
                return
            if context.stop_requested():
                raise InterruptedError("LiveKit startup interrupted")
            time.sleep(self.readiness_interval)
        raise RuntimeError("deployment/livekit startup readiness timed out")

    def start(self, context: RuntimeContext) -> Identity:
        before = self._deployment(context)
        if before is None or not self._approved(before):
            raise RuntimeError("approved deployment/livekit is missing or has an unexpected spec")
        identity = self._identity(before)
        if identity is None or identity["replicas"] not in {0, 1}:
            raise RuntimeError("deployment/livekit has an invalid identity or replica count")
        if identity["replicas"] == 0:
            if context.stop_requested():
                raise InterruptedError("stop requested before starting LiveKit")
            after = self._patch_replicas(context, before, 1)
            partial = self._identity(after or {}) or {**identity, "ownership_unconfirmed": True, "target_replicas": 1}
            if after is None or not self._approved(after) or not self._expected_transition(before, after, 1):
                raise PartialStartError("deployment/livekit scale-up was not confirmed", partial)
            identity = self._identity(after)
            if identity is None:
                raise PartialStartError("deployment/livekit identity was not captured", partial)
        try:
            self._wait_ready(context, identity)
        except Exception as error:
            raise PartialStartError(str(error), identity) from error
        return identity

    def owns(self, context: RuntimeContext, identity: Identity) -> bool:
        snapshot = self._deployment(context)
        return snapshot is not None and self._matches_identity(snapshot, identity)

    def is_running(self, context: RuntimeContext, identity: Identity) -> bool | None:
        if identity.get("ownership_unconfirmed") is True:
            return None
        snapshot = self._deployment(context)
        return None if snapshot is None else self._matches_identity(snapshot, identity) and snapshot.get("spec", {}).get("replicas") == 1

    def stop(self, context: RuntimeContext, identity: Identity) -> None:
        before = self._deployment(context)
        if before is None or not self._matches_identity(before, identity):
            raise RuntimeError("deployment/livekit identity changed; refusing cleanup")
        if identity.get("replicas") != 1:
            raise RuntimeError("owned deployment/livekit replica count is invalid")
        after = self._patch_replicas(context, before, 0)
        if after is None or not self._approved(after) or not self._expected_transition(before, after, 0):
            raise RuntimeError("deployment/livekit scale-down was not confirmed")
