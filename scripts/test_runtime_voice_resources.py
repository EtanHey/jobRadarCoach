import copy
import json
import subprocess

import pytest

from scripts.runtime_control import PartialStartError, Supervisor
from scripts.runtime_process import RuntimeContext
from scripts.runtime_voice_resources import KokoroContainerService


CONTAINER_ID = "a" * 64
IMAGE_ID = "sha256:" + "b" * 64
STARTED_AT = "2026-09-09T10:00:00.000000000Z"


def snapshot(*, running=True, started_at=STARTED_AT):
    return {
        "Id": CONTAINER_ID,
        "Image": IMAGE_ID,
        "Name": "/kokoro",
        "Config": {
            "Image": "ghcr.io/remsky/kokoro-fastapi-cpu:latest",
            "Entrypoint": None,
            "Cmd": ["./entrypoint.sh"],
        },
        "HostConfig": {
            "PortBindings": {"8880/tcp": [{"HostIp": "", "HostPort": "8881"}]},
            "RestartPolicy": {"Name": "no", "MaximumRetryCount": 0},
            "AutoRemove": False,
            "NetworkMode": "bridge",
        },
        "Mounts": [],
        "State": {
            "Running": running,
            "Status": "running" if running else "exited",
            "StartedAt": started_at,
        },
    }


class FakeContext:
    def __init__(self):
        self.commands = []
        self.stop = False

    def stop_requested(self):
        return self.stop

    def run(self, command, **_kwargs):
        self.commands.append(tuple(command))
        return subprocess.CompletedProcess(command, 0, "", "")


def test_probe_requires_the_approved_installed_shape(monkeypatch):
    context = FakeContext()
    service = KokoroContainerService()
    wrong = snapshot()
    wrong["HostConfig"]["PortBindings"]["8880/tcp"][0]["HostPort"] = "9999"
    monkeypatch.setattr(service, "_inspect", lambda *_args: wrong)
    monkeypatch.setattr(service, "_health", lambda *_args: pytest.fail("must not probe"))

    probe = service.probe(context)
    assert not probe.healthy
    assert probe.detail == "approved Kokoro container is missing or unidentified"

    wrong = snapshot()
    wrong["Id"] = CONTAINER_ID[:12]
    monkeypatch.setattr(service, "_inspect", lambda *_args: wrong)
    assert not service.probe(context).healthy


def test_healthy_container_is_adopted_with_exact_identity(monkeypatch):
    context = FakeContext()
    service = KokoroContainerService()
    current = snapshot()
    monkeypatch.setattr(service, "_inspect", lambda *_args: current)
    monkeypatch.setattr(service, "_health", lambda *_args: True)

    assert service.lifecycle_owned is True
    assert service.start(context) == {
        "container_id": CONTAINER_ID,
        "image_id": IMAGE_ID,
        "started_at": STARTED_AT,
    }
    assert context.commands == []


def test_stopped_container_starts_and_stops_by_full_identity(monkeypatch):
    context = FakeContext()
    service = KokoroContainerService(startup_timeout=0.1, readiness_interval=0)
    current = snapshot(running=False, started_at="0001-01-01T00:00:00Z")

    def inspect(_context, _reference):
        return copy.deepcopy(current)

    def run(command, **_kwargs):
        context.commands.append(tuple(command))
        if command[2] == "start":
            current.update(snapshot())
        elif command[2] == "stop":
            current["State"]["Running"] = False
            current["State"]["Status"] = "exited"
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(service, "_inspect", inspect)
    monkeypatch.setattr(service, "_health", lambda *_args: True)
    monkeypatch.setattr(context, "run", run)

    identity = service.start(context)
    assert service.owns(context, identity)
    assert service.is_running(context, identity) is True
    service.stop(context, identity)
    assert context.commands == [
        ("docker", "container", "start", CONTAINER_ID),
        ("docker", "container", "stop", "--time", "10", CONTAINER_ID),
    ]
    assert not current["State"]["Running"]
    assert service.is_running(context, identity) is False


def test_post_mutation_readiness_failure_preserves_partial_identity(monkeypatch):
    context = FakeContext()
    service = KokoroContainerService(startup_timeout=0)
    before = snapshot(running=False, started_at="0001-01-01T00:00:00Z")
    after = snapshot()
    values = iter((before, after))
    monkeypatch.setattr(service, "_inspect", lambda *_args: next(values))
    monkeypatch.setattr(service, "_health", lambda *_args: False)

    with pytest.raises(PartialStartError, match="health check timed out") as caught:
        service.start(context)
    assert caught.value.owned_identity == {
        "container_id": CONTAINER_ID,
        "image_id": IMAGE_ID,
        "started_at": STARTED_AT,
    }


def test_successful_start_without_post_start_inspect_retains_unconfirmed_identity(monkeypatch):
    context = FakeContext()
    service = KokoroContainerService()
    before = snapshot(running=False, started_at="0001-01-01T00:00:00Z")
    values = iter((before, None, None, None))
    monkeypatch.setattr(service, "_inspect", lambda *_args: next(values))
    monkeypatch.setattr("scripts.runtime_voice_resources.time.sleep", lambda _seconds: None)

    with pytest.raises(PartialStartError, match="identity could not be confirmed") as caught:
        service.start(context)

    identity = caught.value.owned_identity
    assert identity == {
        "container_id": CONTAINER_ID,
        "image_id": IMAGE_ID,
        "ownership_status": "unconfirmed_after_start",
    }
    assert "started_at" not in identity
    assert not service.owns(context, identity)
    assert service.is_running(context, identity) is None
    with pytest.raises(RuntimeError, match="identity was unconfirmed; refusing cleanup"):
        service.stop(context, identity)
    assert context.commands == [("docker", "container", "start", CONTAINER_ID)]


def test_resource_liveness_is_unknown_when_inspect_is_unavailable(monkeypatch):
    context = FakeContext()
    service = KokoroContainerService()
    identity = {
        "container_id": CONTAINER_ID,
        "image_id": IMAGE_ID,
        "started_at": STARTED_AT,
    }
    monkeypatch.setattr(service, "_inspect", lambda *_args: None)

    assert service.is_running(context, identity) is None


def test_supervisor_retains_unconfirmed_identity_and_cleanup_refusal(monkeypatch, tmp_path):
    context = RuntimeContext(tmp_path, tmp_path / "state")
    service = KokoroContainerService()
    before = snapshot(running=False, started_at="0001-01-01T00:00:00Z")
    values = iter((before, before, None, None, None))
    commands = []

    def result(_context, command, **_kwargs):
        commands.append(tuple(command))
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(service, "_inspect", lambda *_args: next(values))
    monkeypatch.setattr(service, "_result", result)
    monkeypatch.setattr("scripts.runtime_voice_resources.time.sleep", lambda _seconds: None)

    assert Supervisor(context, [service]).up() == 1
    retained = json.loads((context.state_dir / "state.json").read_text())
    assert retained["services"] == [{
        "name": "kokoro",
        "mode": "owned",
        "identity": {
            "container_id": CONTAINER_ID,
            "image_id": IMAGE_ID,
            "ownership_status": "unconfirmed_after_start",
        },
    }]
    assert retained["cleanup_failures"] == [
        "kokoro: cleanup failed: ownership identity changed; refusing cleanup"
    ]
    assert commands == [("docker", "container", "start", CONTAINER_ID)]


def test_recovered_post_start_inspect_confirms_identity_and_supports_cleanup(monkeypatch):
    context = FakeContext()
    service = KokoroContainerService(startup_timeout=0.1, readiness_interval=0)
    current = snapshot(running=False, started_at="0001-01-01T00:00:00Z")
    inspect_count = 0

    def inspect(_context, _reference):
        nonlocal inspect_count
        inspect_count += 1
        if inspect_count == 2:
            return None
        return copy.deepcopy(current)

    def run(command, **_kwargs):
        context.commands.append(tuple(command))
        if command[2] == "start":
            current.update(snapshot())
        elif command[2] == "stop":
            current["State"]["Running"] = False
            current["State"]["Status"] = "exited"
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(service, "_inspect", inspect)
    monkeypatch.setattr(service, "_health", lambda *_args: True)
    monkeypatch.setattr(context, "run", run)
    monkeypatch.setattr("scripts.runtime_voice_resources.time.sleep", lambda _seconds: None)

    identity = service.start(context)
    assert identity == {
        "container_id": CONTAINER_ID,
        "image_id": IMAGE_ID,
        "started_at": STARTED_AT,
    }
    service.stop(context, identity)
    assert context.commands == [
        ("docker", "container", "start", CONTAINER_ID),
        ("docker", "container", "stop", "--time", "10", CONTAINER_ID),
    ]


def test_stopped_container_cannot_pass_readiness_from_unrelated_endpoint(monkeypatch):
    context = FakeContext()
    service = KokoroContainerService(startup_timeout=0.1, readiness_interval=0)
    before = snapshot(running=False, started_at="0001-01-01T00:00:00Z")
    started = snapshot()
    stopped = snapshot(running=False)
    values = iter((before, started, stopped))
    monkeypatch.setattr(service, "_inspect", lambda *_args: next(values))
    monkeypatch.setattr(service, "_health", lambda *_args: True)

    with pytest.raises(PartialStartError, match="stopped during readiness"):
        service.start(context)


def test_stop_refuses_same_container_restarted_after_adoption(monkeypatch):
    context = FakeContext()
    service = KokoroContainerService()
    restarted = snapshot(started_at="2026-09-09T11:00:00.000000000Z")
    monkeypatch.setattr(service, "_inspect", lambda *_args: restarted)
    identity = {
        "container_id": CONTAINER_ID,
        "image_id": IMAGE_ID,
        "started_at": STARTED_AT,
    }

    assert not service.owns(context, identity)
    assert service.is_running(context, identity) is False
    with pytest.raises(RuntimeError, match="identity changed"):
        service.stop(context, identity)
    assert context.commands == []


def test_inspect_rejects_malformed_or_ambiguous_docker_output():
    service = KokoroContainerService()

    class Context(FakeContext):
        def __init__(self, output):
            super().__init__()
            self.output = output

        def run(self, command, **_kwargs):
            return subprocess.CompletedProcess(command, 0, self.output, "")

    for output in ("not-json", json.dumps([]), json.dumps([{}, {}]), json.dumps([None])):
        assert service._inspect(Context(output), "kokoro") is None
