import json
import subprocess

import pytest

from scripts.runtime_control import PartialStartError
from scripts.runtime_livekit_resource import LiveKitDeploymentService
from scripts.runtime_process import Probe


UID = "083fbdaa-4adb-4166-841f-888907f1658b"


def deployment(*, replicas=1, generation=4, ready=True):
    status = {"observedGeneration": generation, "updatedReplicas": 1, "readyReplicas": 1, "availableReplicas": 1} if ready else {}
    return {
        "apiVersion": "apps/v1", "kind": "Deployment",
        "metadata": {"name": "livekit", "namespace": "job-radar-coach", "uid": UID, "generation": generation},
        "spec": {
            "replicas": replicas, "selector": {"matchLabels": {"app": "livekit"}},
            "template": {
                "metadata": {"labels": {"app": "livekit"}},
                "spec": {
                    "enableServiceLinks": False,
                    "containers": [{
                        "name": "livekit", "image": "livekit/livekit-server:latest",
                        "args": ["--config", "/etc/livekit/livekit.yaml"],
                        "ports": [
                            {"containerPort": 7880}, {"containerPort": 7881, "protocol": "TCP"},
                            {"containerPort": 50000, "protocol": "UDP"},
                        ],
                        "env": [
                            {"name": "NODE_IP", "valueFrom": {"configMapKeyRef": {"key": "node_ip", "name": "livekit-advertise"}}},
                            {"name": "LIVEKIT_API_KEY", "valueFrom": {"secretKeyRef": {"key": "LIVEKIT_API_KEY", "name": "livekit-keys"}}},
                            {"name": "LIVEKIT_API_SECRET", "valueFrom": {"secretKeyRef": {"key": "LIVEKIT_API_SECRET", "name": "livekit-keys"}}},
                            {"name": "LIVEKIT_KEYS", "value": "$(LIVEKIT_API_KEY): $(LIVEKIT_API_SECRET)"},
                        ],
                        "volumeMounts": [{"name": "config", "mountPath": "/etc/livekit"}],
                    }],
                    "volumes": [{"name": "config", "configMap": {"name": "livekit-config"}}],
                },
            },
        },
        "status": status,
    }


class Context:
    def stop_requested(self):
        return False


def healthy_prerequisite(*_args):
    return Probe(True, "ready")


def test_healthy_deployment_is_adopted_with_exact_identity(monkeypatch):
    service, current = LiveKitDeploymentService(), deployment()
    monkeypatch.setattr(service, "_deployment", lambda *_args: current)
    monkeypatch.setattr(service, "_prerequisites", healthy_prerequisite)
    monkeypatch.setattr(service, "_patch_replicas", lambda *_args: pytest.fail("must not patch"))

    identity = service.start(Context())
    assert service.lifecycle_owned is True
    assert identity == service._identity(current)
    assert identity == {"deployment_uid": UID, "generation": 4, "spec_sha256": identity["spec_sha256"], "replicas": 1}
    assert service.owns(Context(), identity)
    assert service.is_running(Context(), identity)

    service.startup_timeout = 0
    monkeypatch.setattr(service, "_deployment", lambda *_args: deployment(ready=False))
    with pytest.raises(PartialStartError) as caught:
        service.start(Context())
    assert caught.value.owned_identity == service._identity(deployment(ready=False))


def test_scale_up_and_down_require_exact_transition(monkeypatch):
    service = LiveKitDeploymentService(startup_timeout=0.1, readiness_interval=0)
    before, running, stopped = deployment(replicas=0, ready=False), deployment(generation=5), deployment(replicas=0, generation=6, ready=False)
    current = [before]
    monkeypatch.setattr(service, "_deployment", lambda *_args: current[0])
    monkeypatch.setattr(service, "_prerequisites", healthy_prerequisite)

    def patch(_context, snapshot, target):
        assert snapshot is current[0]
        current[0] = running if target == 1 else stopped
        return current[0]

    monkeypatch.setattr(service, "_patch_replicas", patch)
    identity = service.start(Context())
    assert identity == service._identity(running)
    service.stop(Context(), identity)
    assert current[0]["spec"]["replicas"] == 0


def test_patch_uses_atomic_uid_generation_and_replica_tests(monkeypatch):
    service, before, after = LiveKitDeploymentService(), deployment(replicas=0, ready=False), deployment(generation=5)
    captured = []

    def result(_context, command, **_kwargs):
        captured.append(command)
        return subprocess.CompletedProcess(command, 0, json.dumps(after), "")

    monkeypatch.setattr(service, "_result", result)
    assert service._patch_replicas(Context(), before, 1) == after
    patch = json.loads(captured[0][captured[0].index("-p") + 1])
    assert patch == [{"op": "test", "path": "/metadata/uid", "value": UID}, {"op": "test", "path": "/metadata/generation", "value": 4}, {"op": "test", "path": "/spec/replicas", "value": 0}, {"op": "replace", "path": "/spec/replicas", "value": 1}]


def test_prerequisites_require_exact_service_ports_and_advertise_data(monkeypatch):
    service = LiveKitDeploymentService()
    resources = {
        "service/livekit": {"spec": {"ports": [{"port": 7880, "targetPort": 7880}, {"port": 7881, "targetPort": 7881}, {"port": 50000, "targetPort": 50000, "protocol": "UDP"}]}},
        "configmap/livekit-advertise": {"data": {"node_ip": "100.64.0.1"}},
    }
    monkeypatch.setattr(service, "_get", lambda _context, resource: resources[resource])
    monkeypatch.setattr(service, "_result", lambda *_args, **_kwargs: subprocess.CompletedProcess([], 0, "100.64.0.1\n", ""))
    assert service._prerequisites(Context()).healthy
    resources["service/livekit"]["spec"]["ports"].append({"port": 9999, "targetPort": 9999})
    assert not service._prerequisites(Context()).healthy
    resources["service/livekit"]["spec"]["ports"].pop()
    resources["configmap/livekit-advertise"]["data"]["extra"] = "ambiguous"
    assert not service._prerequisites(Context()).healthy


def test_post_mutation_failure_preserves_exact_owned_identity(monkeypatch):
    service = LiveKitDeploymentService(startup_timeout=0)
    before, running = deployment(replicas=0, ready=False), deployment(generation=5, ready=False)
    monkeypatch.setattr(service, "_deployment", lambda *_args: before)
    monkeypatch.setattr(service, "_patch_replicas", lambda *_args: running)

    with pytest.raises(PartialStartError, match="readiness timed out") as caught:
        service.start(Context())
    assert caught.value.owned_identity == service._identity(running)


@pytest.mark.parametrize("failure", ("generation", "spec"))
def test_unexpected_valid_patch_response_is_never_claimed(monkeypatch, failure):
    service = LiveKitDeploymentService()
    before, after = deployment(replicas=0, ready=False), deployment(generation=5)
    if failure == "generation":
        after["metadata"]["generation"] = 6
        after["status"]["observedGeneration"] = 6
    else:
        after["spec"]["strategy"] = {"type": "Recreate"}
    monkeypatch.setattr(service, "_deployment", lambda *_args: before)
    monkeypatch.setattr(service, "_patch_replicas", lambda *_args: after)

    with pytest.raises(PartialStartError, match="scale-up was not confirmed") as caught:
        service.start(Context())
    unconfirmed = caught.value.owned_identity
    assert unconfirmed == {
        "ownership_unconfirmed": True, "target_replicas": 1,
        "before_identity": service._identity(before), "observed_identity": service._identity(after),
    }
    assert service.is_running(Context(), unconfirmed) is None
    assert not service.owns(Context(), unconfirmed)
    with pytest.raises(RuntimeError, match="ownership unconfirmed"):
        service.stop(Context(), unconfirmed)


def test_identity_or_spec_change_refuses_cleanup(monkeypatch):
    service, original = LiveKitDeploymentService(), deployment()
    identity, changed = service._identity(original), deployment()
    changed["spec"]["template"]["spec"]["containers"][0]["image"] = "unapproved"
    monkeypatch.setattr(service, "_deployment", lambda *_args: changed)
    monkeypatch.setattr(service, "_patch_replicas", lambda *_args: pytest.fail("must not patch"))

    assert identity is not None and not service.owns(Context(), identity)
    assert not service.is_running(Context(), identity)
    monkeypatch.setattr(service, "_deployment", lambda *_args: None)
    assert (service.is_running(Context(), identity), service.is_running(Context(), {**identity, "ownership_unconfirmed": True})) == (None, None)
    with pytest.raises(RuntimeError, match="identity changed"):
        service.stop(Context(), identity)


def test_scaled_down_deployment_is_not_ready_despite_stale_status(monkeypatch):
    service, stopped = LiveKitDeploymentService(), deployment(replicas=0)
    monkeypatch.setattr(service, "_deployment", lambda *_args: stopped)
    monkeypatch.setattr(service, "_prerequisites", lambda *_args: pytest.fail("must not probe"))

    probe = service.probe(Context())
    assert not probe.healthy
    assert probe.detail == "approved deployment/livekit is scaled down"
