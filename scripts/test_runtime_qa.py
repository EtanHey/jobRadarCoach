import hashlib
import json
import os
from pathlib import Path
import subprocess

import pytest

import scripts.runtime_qa as subject
from scripts.runtime_process import RuntimeContext


def configured(monkeypatch):
    values = {
        "LIVEKIT_API_KEY": "private-key", "LIVEKIT_API_SECRET": "private-secret",
        "UI_ORIGIN": "https://ui.test", "VOICE_QA_EXPECTED_LIVEKIT_URL": "ws://127.0.0.1:7880",
        "LIVEKIT_PUBLIC_URL": "wss://voice.test",
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)


def pin_verifier(monkeypatch, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# synthetic released verifier\n")
    monkeypatch.setattr(subject, "_VERIFIER_SHA256", hashlib.sha256(path.read_bytes()).hexdigest())


def test_verifier_refuses_missing_receipt_before_start(monkeypatch, tmp_path):
    configured(monkeypatch)
    repo = tmp_path
    verifier = repo / "scripts/verify_agent_qa_receipt.py"
    pin_verifier(monkeypatch, verifier)
    verifier.write_text(
        "import json\nprint(json.dumps({'status':'NOT_READY','reason':'receipt_missing'},"
        "separators=(',', ':')))\nraise SystemExit(1)\n"
    )
    monkeypatch.setattr(subject, "_VERIFIER_SHA256", hashlib.sha256(verifier.read_bytes()).hexdigest())
    monkeypatch.setenv("VOICE_QA_RECEIPT_FILE", str(tmp_path / "absent.json"))
    monkeypatch.setenv("VOICE_QA_VERIFIER_FILE", str(verifier))
    context = RuntimeContext(repo_root=repo, state_dir=tmp_path / "state", qa_mode=True)
    with pytest.raises(RuntimeError, match="QA NOT READY: receipt_missing"):
        subject.QaRuntimeService().start(context)
    assert not (context.state_dir / "qa-runtime.json").exists()


def test_verifier_v2_mode_reason_hash_and_command_contract(monkeypatch, tmp_path):
    verifier = tmp_path / "verifier.py"
    pin_verifier(monkeypatch, verifier)
    receipt = tmp_path / "receipt.json"
    service, context = subject.QaRuntimeService(), FakeContext(tmp_path)
    responses = iter([
        subprocess.CompletedProcess((), 0,
            '{"status":"READY","mode":"qa","worker_id":"AW_fixture"}\n', ""),
        subprocess.CompletedProcess((), 0,
            '{"status":"READY","mode":"normal","worker_id":"AW_fixture"}\n', ""),
        subprocess.CompletedProcess((), 1,
            '{"status":"NOT_READY","reason":"wrong_mode"}\n',
            "NOT_READY verifier_failed legacy\n"),
        subprocess.CompletedProcess((), 1, "", "NOT_READY worker_not_registered legacy\n"),
    ])

    def run(command, **kwargs):
        context.commands.append((tuple(command), kwargs))
        return next(responses)

    context.run = run
    assert service._verify(context, verifier, receipt, "ws://local") == ("AW_fixture", "")
    assert service._verify(context, verifier, receipt, "ws://local") == (
        None, "verifier_output_invalid",
    )
    assert service._verify(context, verifier, receipt, "ws://local") == (None, "wrong_mode")
    assert service._verify(context, verifier, receipt, "ws://local") == (
        None, "worker_not_registered",
    )
    assert all(call[0][1:4] == (str(verifier), "--require-mode", "qa") for call in context.commands)
    monkeypatch.setattr(subject, "_VERIFIER_SHA256", "0" * 64)
    assert service._verify(context, verifier, receipt, "ws://local") == (
        None, "verifier_hash_mismatch",
    )
    assert len(context.commands) == 4


def test_probe_reverifies_instead_of_trusting_ready_marker(monkeypatch, tmp_path):
    configured(monkeypatch)
    context = FakeContext(tmp_path)
    context.state_dir.mkdir(parents=True)
    marker = {
        "status": "READY", "reason": None, "session_id": "session",
        "worker_id": "AW_fixture", "supervisor_pid": os.getpid(), "qa_url": "http://qa.test",
    }
    (context.state_dir / "qa-runtime.json").write_text(json.dumps(marker))
    service = subject.QaRuntimeService(receipt_provider=lambda _context: tmp_path / "receipt.json")
    service._session_id = "session"
    answers = iter([("AW_fixture", ""), (None, "worker_not_registered")])
    calls = []

    def verify(*args):
        calls.append(args)
        return next(answers)

    monkeypatch.setattr(service, "_verify", verify)
    assert service.probe(context).healthy
    second = service.probe(context)
    assert not second.healthy and second.detail == "QA NOT READY: worker_not_registered"
    assert len(calls) == 2


def test_equal_qa_and_normal_receipt_paths_refuse_before_config(monkeypatch, tmp_path):
    shared = tmp_path / "shared.json"
    monkeypatch.setenv("VOICE_QA_RECEIPT_FILE", shared.name)
    monkeypatch.setenv("AGENT_NORMAL_RECEIPT_FILE", str(shared.parent / "." / shared.name))
    service = subject.QaRuntimeService()
    monkeypatch.setattr(service, "_config", lambda _context: pytest.fail("config read ran"))

    with pytest.raises(RuntimeError, match="receipt_path_conflict"):
        service.start(FakeContext(tmp_path))


def test_receipt_provider_selects_receipt_without_changing_default_fallback(monkeypatch, tmp_path):
    configured(monkeypatch)
    context = FakeContext(tmp_path)
    selected = tmp_path / "selected-agent.json"
    service = subject.QaRuntimeService(receipt_provider=lambda received: selected if received is context else Path())
    observed = []

    def verify(_context, _verifier, receipt, _server):
        observed.append(receipt)
        return None, "receipt_missing"

    monkeypatch.setattr(service, "_verify", verify)
    with pytest.raises(RuntimeError, match="receipt_missing"):
        service.start(context)
    assert observed == [selected]


class FakeContext:
    qa_mode = True

    def __init__(self, root):
        self.repo_root, self.state_dir = root, root / "state"
        self.commands = []

    def run(self, command, **_kwargs):
        self.commands.append(tuple(command))
        return subprocess.CompletedProcess(command, 0, "", "")


class FakeProcess:
    stopped = False

    def __init__(self, *_args, env=None, **_kwargs):
        self.env = env

    def start(self, _context):
        return {"pid": 9, "pgid": 9, "start": "fixture"}

    def owns(self, _context, _identity):
        return True

    def stop(self, _context, _identity):
        self.stopped = True


def test_phone_mapping_owns_and_removes_only_selected_target(monkeypatch, tmp_path):
    configured(monkeypatch)
    monkeypatch.setenv("VOICE_QA_PHONE", "1")
    monkeypatch.setattr(subject, "ProcessService", FakeProcess)
    service, context = subject.QaRuntimeService(), FakeContext(tmp_path)
    monkeypatch.setattr(service, "_verify", lambda *_args: ("AW_fixture", ""))
    monkeypatch.setattr(service, "_free_loopback_port", lambda: 4567)
    monkeypatch.setattr(service, "_serve", lambda _ctx: ({"port": 8473, "dns": "host.ts.net"}, "https://host.ts.net:8473"))
    target = [None]
    monkeypatch.setattr(service, "_mapping_target", lambda *_args: target[0])

    def run(command, **_kwargs):
        context.commands.append(tuple(command))
        if command[:3] == ("tailscale", "serve", "--bg"):
            target[0] = "http://127.0.0.1:4567"
        elif command[:2] == ("tailscale", "serve") and command[-1] == "off":
            target[0] = None
        return subprocess.CompletedProcess(command, 0, "", "")

    context.run = run
    identity = service.start(context)
    assert identity["mapping"] == {
        "port": 8473, "dns": "host.ts.net", "target": "http://127.0.0.1:4567",
    }
    assert "private-key" not in json.dumps(identity) and "private-secret" not in json.dumps(identity)
    service.stop(context, identity)
    assert context.commands[-1] == ("tailscale", "serve", "--https=8473", "off")


def test_build_requires_qa_mode(tmp_path):
    context = RuntimeContext(repo_root=tmp_path, state_dir=tmp_path / "state")
    with pytest.raises(RuntimeError, match="requires --qa"):
        subject.build_qa_services(context)


def test_changed_foreign_mapping_is_untouched_but_proxy_stops(monkeypatch, tmp_path):
    service, context = subject.QaRuntimeService(), FakeContext(tmp_path)
    process = FakeProcess()
    service._process = process
    monkeypatch.setattr(service, "_mapping_target", lambda *_args: "http://foreign:9999")
    identity = {
        "session_id": "fixture", "process": {"pid": 9},
        "mapping": {"port": 8473, "dns": "host.ts.net", "target": "http://127.0.0.1:4567"},
    }
    with pytest.raises(RuntimeError, match="mapping changed"):
        service.stop(context, identity)
    assert process.stopped
    assert context.commands == []


def test_mapping_status_unknown_after_apply_retains_partial_identity(monkeypatch, tmp_path):
    configured(monkeypatch)
    monkeypatch.setenv("VOICE_QA_PHONE", "1")
    monkeypatch.setattr(subject, "ProcessService", FakeProcess)
    service, context = subject.QaRuntimeService(), FakeContext(tmp_path)
    monkeypatch.setattr(service, "_verify", lambda *_args: ("AW_fixture", ""))
    monkeypatch.setattr(service, "_free_loopback_port", lambda: 4567)
    monkeypatch.setattr(service, "_serve", lambda _ctx: ({"port": 8473, "dns": "host.ts.net"}, "https://host.ts.net:8473"))
    attempted = False

    def run(command, **_kwargs):
        nonlocal attempted
        context.commands.append(tuple(command))
        if command[:3] == ("tailscale", "serve", "--bg"):
            attempted = True
        return subprocess.CompletedProcess(command, 0, "", "")

    context.run = run
    monkeypatch.setattr(subject, "_json", lambda *_args: None if attempted else {"TCP": {}, "Web": {}})
    with pytest.raises(subject.PartialStartError) as caught:
        service.start(context)
    assert caught.value.owned_identity["mapping"]["target"] == "http://127.0.0.1:4567"
    assert service._process.stopped


def test_unknown_stop_mapping_is_retained_then_recoverable(monkeypatch, tmp_path):
    service, context = subject.QaRuntimeService(), FakeContext(tmp_path)
    process = FakeProcess()
    service._process = process
    mapping = {"port": 8473, "dns": "host.ts.net", "target": "http://127.0.0.1:4567"}
    identity = {"session_id": "fixture", "process": {"pid": 9}, "mapping": mapping}
    monkeypatch.setattr(subject, "_json", lambda *_args: None)
    with pytest.raises(RuntimeError, match="status unavailable"):
        service.stop(context, identity)
    assert process.stopped
    assert context.commands == []

    active = True

    def status(*_args):
        return {"TCP": {"8473": {"HTTPS": True}}, "Web": {"host.ts.net:8473": {"Handlers": {"/": {"Proxy": mapping["target"]}}}}} if active else {"TCP": {}, "Web": {}}

    def run(command, **_kwargs):
        nonlocal active
        context.commands.append(tuple(command))
        if command[-1] == "off":
            active = False
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(subject, "_json", status)
    context.run = run
    service.stop(context, identity)
    assert context.commands[-1] == ("tailscale", "serve", "--https=8473", "off")
