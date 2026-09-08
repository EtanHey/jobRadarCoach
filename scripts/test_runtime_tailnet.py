import subprocess

import pytest

import scripts.runtime_tailnet as subject


class FakeContext:
    def __init__(self):
        self.commands = []

    def stop_requested(self):
        return False

    def run(self, command, **_kwargs):
        self.commands.append(tuple(command))
        return subprocess.CompletedProcess(command, 0, "", "")


def test_creates_and_removes_only_missing_exact_mappings(monkeypatch):
    context, service = FakeContext(), subject.TailscaleServeService()
    targets = {"https:8445": service.desired["https:8445"], "https:8446": None, "tcp:7881": None}
    monkeypatch.setattr(service, "_targets", lambda _context: dict(targets))
    monkeypatch.setattr(subject, "_json", lambda *_args: {"Self": {"DNSName": "host.ts.net."}})
    monkeypatch.setattr(subject, "_http", lambda *_args: True)
    original_run = context.run

    def run(command, **kwargs):
        result = original_run(command, **kwargs)
        flag = next((item for item in command if item.startswith(("--https=", "--tcp="))), None)
        if flag and command[-1] != "off":
            kind, port = flag[2:].split("=")
            targets[f"{kind}:{port}"] = service.desired[f"{kind}:{port}"]
        elif flag:
            kind, port = flag[2:].split("=")
            targets[f"{kind}:{port}"] = None
        return result

    context.run = run
    identity = service.start(context)
    assert identity["created"] == ["https:8446", "tcp:7881"] and service.owns(context, identity)
    service.stop(context, identity)
    assert [command[-2:] for command in context.commands[-2:]] == [
        ("--tcp=7881", "off"), ("--https=8446", "off"),
    ]


def test_refuses_conflicting_mapping_without_mutation(monkeypatch):
    context, service = FakeContext(), subject.TailscaleServeService()
    monkeypatch.setattr(service, "_targets", lambda _context: {
        **service.desired, "https:8445": "http://127.0.0.1:9999",
    })
    with pytest.raises(RuntimeError, match="refusing to replace"):
        service.start(context)
    assert context.commands == []


def test_parser_treats_non_https_occupied_port_as_conflict(monkeypatch):
    service, context = subject.TailscaleServeService(), FakeContext()
    values = iter([
        {"TCP": {"8445": {"TCPForward": "127.0.0.1:9999"}}, "Web": {}},
        {"Self": {"DNSName": "host.ts.net."}},
    ])
    monkeypatch.setattr(subject, "_json", lambda *_args: next(values))
    assert service._targets(context)["https:8445"] == "<occupied>"


def test_timeout_after_apply_is_detected_and_rolled_back(monkeypatch):
    context, service = FakeContext(), subject.TailscaleServeService()
    targets = {key: None for key in service.desired}
    monkeypatch.setattr(service, "_targets", lambda _context: dict(targets))

    def result(_context, command):
        flag = next(item for item in command if item.startswith(("--https=", "--tcp=")))
        key = flag[2:].replace("=", ":")
        targets[key] = None if command[-1] == "off" else service.desired[key]
        return subprocess.CompletedProcess(command, 0, "", "") if command[-1] == "off" else None

    monkeypatch.setattr(subject, "_result", result)
    with pytest.raises(RuntimeError, match="failed to create"):
        service.start(context)
    assert targets["https:8445"] is None


def test_unconfirmed_rollback_preserves_partial_identity(monkeypatch):
    context, service = FakeContext(), subject.TailscaleServeService()
    targets = {key: None for key in service.desired}
    monkeypatch.setattr(service, "_targets", lambda _context: dict(targets))

    def result(_context, command):
        key = next(item for item in command if item.startswith(("--https=", "--tcp=")))[2:].replace("=", ":")
        if command[-1] != "off":
            targets[key] = service.desired[key]
            return None
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(subject, "_result", result)
    with pytest.raises(subject.PartialStartError) as caught:
        service.start(context)
    assert caught.value.owned_identity["created"] == ["https:8445"]
