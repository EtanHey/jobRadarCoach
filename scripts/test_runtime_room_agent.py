import json
import hashlib
import subprocess

import pytest

from scripts.runtime_process import Probe, RuntimeContext
import scripts.runtime_room_agent as subject


class FakeContext(RuntimeContext):
    def __init__(self, tmp_path, responses=None, qa_mode=False):
        super().__init__(tmp_path, tmp_path / "state", qa_mode=qa_mode)
        self.responses = responses or {}
        self.calls = []

    def run(self, command, **kwargs):
        command = tuple(command)
        self.calls.append((command, kwargs))
        response = self.responses.get(command)
        if response is None:
            raise AssertionError(f"unexpected command: {command}")
        return subprocess.CompletedProcess(command, *response)


def result(stdout="", returncode=0, stderr=""):
    return returncode, stdout, stderr


def receipt(path, pid):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"process": {"pid": pid}}))


def install_verifier(monkeypatch, tmp_path):
    path = tmp_path / "scripts/verify_agent_qa_receipt.py"
    path.parent.mkdir(parents=True)
    path.write_text("# synthetic verifier\n")
    monkeypatch.setattr(subject, "VERIFIER_SHA256", hashlib.sha256(path.read_bytes()).hexdigest())
    return path


def test_default_verifier_requires_normal_v2_output(monkeypatch, tmp_path):
    verifier = install_verifier(monkeypatch, tmp_path)
    path = tmp_path / "receipt.json"
    command = (
        str(tmp_path / ".venv-agent/bin/python"),
        "-c", "# synthetic verifier\n",
        "--require-mode", "normal", str(path),
    )
    context = FakeContext(tmp_path, {command: result(
        '{"worker_id":"AW_normal","mode":"normal","status":"READY"}\n',
    )})
    probe = subject.RoomAgentService()._default_verify(context, path, "ws://expected:7880")
    assert probe == Probe(True, "verified normal worker AW_normal")
    assert context.calls == [(command, {"env": {"LIVEKIT_URL": "ws://expected:7880"}, "timeout": 20})]

    context.responses[command] = result('{"status":"READY","mode":"qa","worker_id":"AW_qa"}\n')
    assert not subject.RoomAgentService()._default_verify(context, path, "ws://expected:7880").healthy
    context.responses[command] = result('{"status":"READY","worker_id":"AW_v1_qa"}\n')
    assert not subject.RoomAgentService()._default_verify(context, path, "ws://expected:7880").healthy

    verifier.write_text("# replaced verifier\n")
    calls = len(context.calls)
    assert subject.RoomAgentService()._default_verify(context, path, "ws://expected:7880") == Probe(
        False, "normal NOT READY: verifier_hash_mismatch",
    )
    assert len(context.calls) == calls


def test_nonzero_verifier_reason_is_preserved(monkeypatch, tmp_path):
    install_verifier(monkeypatch, tmp_path)
    path = tmp_path / "receipt.json"
    command = (
        str(tmp_path / ".venv-agent/bin/python"),
        "-c", "# synthetic verifier\n",
        "--require-mode", "normal", str(path),
    )
    context = FakeContext(tmp_path, {command: result(
        '{"reason":"over_load_threshold","status":"NOT_READY"}\n', returncode=1,
    )})
    assert subject.RoomAgentService()._default_verify(context, path, "ws://expected:7880") == Probe(
        False, "normal NOT READY: over_load_threshold",
    )


def test_process_scan_accepts_exact_start_and_dev_argv_in_repo_cwd(tmp_path):
    (tmp_path / ".venv-agent/bin").mkdir(parents=True)
    (tmp_path / ".venv-agent/bin/python").touch()
    (tmp_path / "agent").mkdir()
    (tmp_path / "agent/main.py").touch()
    (tmp_path / "other").mkdir()
    interpreter = tmp_path / ".venv-agent/bin/python"
    ps = (
        f"41 {interpreter} agent/main.py start\n"
        f"42 {interpreter} agent/main.py dev\n"
        f"43 {interpreter} agent/main.py start --extra\n"
        f"44 {interpreter} agent/main.py start\n"
    )
    responses = {("ps", "-axo", "pid=,command="): result(ps)}
    for pid, cwd in ((41, tmp_path), (42, tmp_path), (43, tmp_path), (44, tmp_path / "other")):
        responses[("lsof", "-a", "-p", str(pid), "-d", "cwd", "-Fn")] = result(f"p{pid}\nn{cwd}\n")
    assert subject._agent_processes(FakeContext(tmp_path, responses)) == {
        41: True, 42: True, 43: False,
    }


def test_process_scan_accepts_same_repo_filesystem_aliases(tmp_path):
    (tmp_path / ".venv-agent/bin").mkdir(parents=True)
    (tmp_path / ".venv-agent/bin/python").touch()
    (tmp_path / "agent").mkdir()
    (tmp_path / "agent/main.py").touch()
    alias = tmp_path.parent / f"{tmp_path.name}-alias"
    alias.symlink_to(tmp_path, target_is_directory=True)
    command = f"51 {alias}/.venv-agent/bin/python {alias}/agent/main.py dev\n"
    responses = {
        ("ps", "-axo", "pid=,command="): result(command),
        ("lsof", "-a", "-p", "51", "-d", "cwd", "-Fn"): result(f"p51\nn{alias}\n"),
    }
    assert subject._agent_processes(FakeContext(tmp_path, responses)) == {51: True}


def test_borrow_requires_verifier_and_sole_matching_receipt_process(monkeypatch, tmp_path):
    path = tmp_path / "normal.json"
    receipt(path, 42)
    (tmp_path / ".venv-agent/bin").mkdir(parents=True)
    interpreter = tmp_path / ".venv-agent/bin/python"
    interpreter.touch()
    (tmp_path / "agent").mkdir()
    (tmp_path / "agent/main.py").touch()
    context = FakeContext(tmp_path, {
        ("ps", "-axo", "pid=,command="): result(f"42 {interpreter} agent/main.py dev\n"),
        ("lsof", "-a", "-p", "42", "-d", "cwd", "-Fn"): result(f"p42\nn{tmp_path}\n"),
    })
    service = subject.RoomAgentService(
        receipt_path=path, url_provider=lambda _context: "ws://expected:7880",
        verifier=lambda *_args: Probe(True, "five normal checks verified"),
    )
    assert service.probe(context) == Probe(True, "five normal checks verified")
    monkeypatch.setattr(subject, "_agent_processes", lambda _context: {42: True, 43: True})
    assert not service.probe(FakeContext(tmp_path)).healthy


def test_owned_start_is_normal_automatic_start_and_cleanup_is_exact(monkeypatch, tmp_path):
    monkeypatch.setenv("VOICE_STT_PORT", "8923")
    context = FakeContext(tmp_path)
    processes = {}
    captured = {}
    monkeypatch.setattr(subject, "_agent_processes", lambda _context: dict(processes))

    class FakeProcess:
        def __init__(self, name, command, probe, **kwargs):
            captured.update(name=name, command=command, probe=probe, **kwargs)
            self._children = {}

        def start(self, _context):
            self._children[777] = object()
            receipt(context.state_dir / "room-agent-receipt.json", 777)
            processes[777] = True
            assert captured["probe"](context).healthy
            return {"pid": 777, "pgid": 777, "start": "fixture"}

        def owns(self, _context, identity):
            return identity.get("pid") == 777

        def stop(self, _context, identity):
            captured["stopped"] = identity

    monkeypatch.setattr(subject, "ProcessService", FakeProcess)
    service = subject.RoomAgentService(
        url_provider=lambda _context: "ws://expected:7880",
        verifier=lambda *_args: Probe(True, "five normal checks verified"),
    )
    monkeypatch.setattr(service, "_config", lambda _context: {
        "DATABASE_URL": "postgres://fixture", "LIVEKIT_API_KEY": "key", "LIVEKIT_API_SECRET": "secret",
    })
    identity = service.start(context)
    assert captured["command"] == (str(tmp_path / ".venv-agent/bin/python"), "agent/main.py", "start")
    assert captured["cwd"] == tmp_path
    assert captured["env"]["LIVEKIT_AGENT_NAME"] == ""
    assert "VOICE_QA_MODE" not in captured["env"]
    assert captured["env"]["STT_URL"] == "http://127.0.0.1:8923/inference"
    assert captured["env"]["AGENT_NORMAL_RECEIPT_FILE"] == str(
        context.state_dir / "room-agent-receipt.json",
    )
    assert service.owns(context, identity)
    service.stop(context, identity)
    assert captured["stopped"] == identity["process"]
    assert not (context.state_dir / "room-agent-receipt.json").exists()
    assert (captured["log_dir"] / "agent.log").exists()
    assert json.loads((captured["log_dir"] / "receipt-snapshot.json").read_text())["process"]["pid"] == 777


def test_existing_or_qa_process_never_starts(monkeypatch, tmp_path):
    monkeypatch.setattr(subject, "_agent_processes", lambda _context: {42: True})
    with pytest.raises(RuntimeError, match="process conflict"):
        subject.RoomAgentService().start(FakeContext(tmp_path))
    with pytest.raises(RuntimeError, match="QA mode requested"):
        subject.RoomAgentService().start(FakeContext(tmp_path, qa_mode=True))


def test_normal_and_qa_receipt_paths_must_differ(monkeypatch, tmp_path):
    same = tmp_path / "same.json"
    monkeypatch.setenv("AGENT_NORMAL_RECEIPT_FILE", str(same))
    monkeypatch.setenv("VOICE_QA_RECEIPT_FILE", str(same))
    service = subject.RoomAgentService(url_provider=lambda _context: "ws://expected:7880")
    assert not service.probe(FakeContext(tmp_path)).healthy


def test_repository_verifier_matches_normal_consumer_contract(tmp_path, monkeypatch, capsys):
    import sys
    from pathlib import Path
    import scripts.verify_agent_qa_receipt as verifier

    source = Path(verifier.__file__)
    assert hashlib.sha256(source.read_bytes()).hexdigest() == subject.VERIFIER_SHA256
    receipt = tmp_path / "synthetic-contract.json"
    receipt.write_text("{}")
    monkeypatch.setattr(sys, "argv", [str(source), "--require-mode", "normal", str(receipt)])

    def validate(value, *, require_mode):
        assert require_mode == "normal"
        return {"schema_version": 2, "mode": require_mode,
                "registration": {"worker_id": "AW_contract"}}

    monkeypatch.setattr(verifier, "validate_receipt", validate)
    monkeypatch.setattr(verifier, "verify_live_load", lambda value: None)
    monkeypatch.setattr(verifier, "verify_pool", lambda value: None)
    assert verifier.main() == 0
    output = capsys.readouterr().out
    assert json.loads(output) == {"status": "READY", "mode": "normal", "worker_id": "AW_contract"}
    assert subject._verifier_result(subprocess.CompletedProcess([], 0, output, "")).healthy


def test_process_scan_accepts_verified_framework_python_alias(tmp_path):
    (tmp_path / ".venv-agent/bin").mkdir(parents=True)
    launcher = tmp_path / ".venv-agent/bin/python"
    launcher.touch()
    framework = tmp_path / "Python"
    framework.touch()
    (tmp_path / "agent").mkdir()
    (tmp_path / "agent/main.py").touch()
    responses = {
        ("ps", "-axo", "pid=,command="): result(f"51 {framework} agent/main.py start\n"),
        ("lsof", "-a", "-p", "51", "-d", "cwd", "-Fn"): result(f"p51\nn{tmp_path}\n"),
        (str(launcher), "-c", subject._INTERPRETER_IDENTITY): result(str(framework) + "\n"),
    }
    assert subject._agent_processes(FakeContext(tmp_path, responses)) == {51: True}
    responses[(str(launcher), "-c", subject._INTERPRETER_IDENTITY)] = result(str(tmp_path / "unrelated") + "\n")
    assert subject._agent_processes(FakeContext(tmp_path, responses)) == {51: False}
