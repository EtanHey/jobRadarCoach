import base64
import hashlib
import json
import subprocess

import pytest

from scripts.runtime_process import Probe, RuntimeContext
import scripts.runtime_qa_agent as subject


class FakeContext(RuntimeContext):
    def __init__(self, tmp_path, responses=None):
        super().__init__(tmp_path, tmp_path / "state", qa_mode=True)
        self.responses = responses or {}
        self.calls = []

    def run(self, command, **kwargs):
        command = tuple(command)
        self.calls.append((command, kwargs))
        response = self.responses.get(command)
        if callable(response):
            response = response(command, kwargs)
        if response is None:
            raise AssertionError(f"unexpected command: {command}")
        return subprocess.CompletedProcess(command, *response)


def result(stdout="", returncode=0, stderr=""):
    return returncode, stdout, stderr


def write_receipt(path, pid):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"process": {"pid": pid}}))


@pytest.fixture(autouse=True)
def released_verifier(monkeypatch, tmp_path):
    verifier = tmp_path / "scripts/verify_agent_qa_receipt.py"
    verifier.parent.mkdir(parents=True, exist_ok=True)
    verifier.write_text("# synthetic released verifier\n")
    monkeypatch.setattr(subject, "_VERIFIER_SHA256", hashlib.sha256(verifier.read_bytes()).hexdigest())


def verifier_command(context, receipt):
    return (
        str(context.repo_root / ".venv-agent/bin/python"),
        "-c", "# synthetic released verifier\n",
        "--require-mode", "qa",
        str(receipt),
    )


def test_verified_existing_worker_is_borrowed(monkeypatch, tmp_path):
    receipt = tmp_path / "borrowed.json"
    write_receipt(receipt, 42)
    context = FakeContext(tmp_path, {
        verifier_command(FakeContext(tmp_path), receipt):
            result('{"status":"READY","worker_id":"worker-1"}\n'),
    })
    monkeypatch.setattr(subject, "_agent_processes", lambda _context: {42: "dev"})
    service = subject.QaAgentService(receipt_path=receipt, url_provider=lambda _context: "ws://local")

    assert service.probe(context) == Probe(True, "verified QA worker worker-1")
    assert service.receipt_path(context) == receipt
    assert all(call[0][0] != "supabase" for call in context.calls)


def test_v2_qa_ready_is_accepted_but_normal_mode_is_rejected(monkeypatch, tmp_path):
    receipt = tmp_path / "borrowed.json"
    write_receipt(receipt, 42)
    command = verifier_command(FakeContext(tmp_path), receipt)
    context = FakeContext(tmp_path, {
        command: result('{"status":"READY","mode":"qa","worker_id":"worker-1"}\n'),
    })
    monkeypatch.setattr(subject, "_agent_processes", lambda _context: {42: "dev"})
    service = subject.QaAgentService(receipt_path=receipt, url_provider=lambda _context: "ws://local")

    assert service.probe(context).healthy
    context.responses[command] = result(
        '{"status":"READY","mode":"normal","worker_id":"worker-1"}\n',
    )
    assert service.probe(context) == Probe(False, "QA NOT READY: verifier_output_invalid")


def test_structured_not_ready_reason_precedes_legacy_stderr_and_every_probe_reverifies(
    monkeypatch, tmp_path,
):
    receipt = tmp_path / "borrowed.json"
    write_receipt(receipt, 42)
    command = verifier_command(FakeContext(tmp_path), receipt)
    responses = iter([
        result('{"status":"NOT_READY","reason":"wrong_mode"}\n', 1,
               "NOT_READY verifier_failed legacy\n"),
        result("", 1, "NOT_READY worker_not_registered legacy\n"),
    ])
    context = FakeContext(tmp_path, {command: lambda *_args: next(responses)})
    monkeypatch.setattr(subject, "_agent_processes", lambda _context: {42: "dev"})
    service = subject.QaAgentService(receipt_path=receipt, url_provider=lambda _context: "ws://local")

    assert service.probe(context) == Probe(False, "QA NOT READY: wrong_mode")
    assert service.probe(context) == Probe(False, "QA NOT READY: worker_not_registered")
    assert [call[0] for call in context.calls] == [command, command]


def test_verifier_hash_change_fails_before_execution(monkeypatch, tmp_path):
    receipt = tmp_path / "borrowed.json"
    write_receipt(receipt, 42)
    context = FakeContext(tmp_path)
    monkeypatch.setattr(subject, "_VERIFIER_SHA256", "0" * 64)
    service = subject.QaAgentService(receipt_path=receipt, url_provider=lambda _context: "ws://local")

    assert service.probe(context) == Probe(False, "QA NOT READY: verifier_hash_mismatch")
    assert context.calls == []


def test_equal_qa_and_normal_receipt_paths_refuse_before_owned_start(monkeypatch, tmp_path):
    shared = tmp_path / "shared.json"
    monkeypatch.setenv("VOICE_QA_RECEIPT_FILE", shared.name)
    monkeypatch.setenv("AGENT_NORMAL_RECEIPT_FILE", str(shared.parent / "." / shared.name))
    monkeypatch.setattr(subject, "_agent_processes", lambda _context: pytest.fail("process scan ran"))

    with pytest.raises(RuntimeError, match="receipt_path_conflict"):
        subject.QaAgentService(url_provider=lambda _context: "ws://local").start(FakeContext(tmp_path))


@pytest.mark.parametrize("processes", [{42: "console"}, {42: "dev", 43: None}])
def test_non_qa_or_unknown_agent_blocks_start(monkeypatch, tmp_path, processes):
    context = FakeContext(tmp_path)
    monkeypatch.setattr(subject, "_agent_processes", lambda _context: processes)
    service = subject.QaAgentService(url_provider=lambda _context: "ws://local")
    with pytest.raises(RuntimeError, match="agent_process_conflict"):
        service.start(context)
    assert context.calls == []


def test_owned_start_uses_private_env_and_binds_receipt_pid(monkeypatch, tmp_path):
    monkeypatch.setenv("VOICE_STT_PORT", "8923")
    context = FakeContext(tmp_path)
    owned_receipt = context.state_dir / "qa-agent-receipt.json"
    context.responses.update({
        ("supabase", "status", "-o", "json", "--workdir", str(tmp_path)):
            result(json.dumps({"DB_URL": "postgres://synthetic"})),
        ("kubectl", "--context", "orbstack", "-n", "job-radar-coach", "get",
         "secret/livekit-keys", "-o", "json"): result(json.dumps({"data": {
             "LIVEKIT_API_KEY": base64.b64encode(b"synthetic-key").decode(),
             "LIVEKIT_API_SECRET": base64.b64encode(b"synthetic-secret").decode(),
         }})),
        verifier_command(context, owned_receipt):
            result('{"status":"READY","worker_id":"owned-worker"}\n'),
    })
    processes = {}
    monkeypatch.setattr(subject, "_agent_processes", lambda _context: dict(processes))
    captured = {}

    class FakeProcessService:
        def __init__(self, name, command, probe, **kwargs):
            captured.update(name=name, command=command, probe=probe, **kwargs)
            self._children = {}

        def start(self, _context):
            self._children[777] = object()
            write_receipt(owned_receipt, 777)
            processes[777] = "dev"
            assert captured["probe"](context).healthy
            return {"pid": 777, "pgid": 777, "start": "synthetic"}

        def owns(self, _context, identity):
            return identity.get("pid") == 777

        def stop(self, _context, identity):
            captured["stopped"] = identity

    monkeypatch.setattr(subject, "ProcessService", FakeProcessService)
    service = subject.QaAgentService(url_provider=lambda _context: "ws://127.0.0.1:7880")
    identity = service.start(context)

    assert captured["command"] == (
        str(tmp_path / ".venv-agent/bin/python"), "agent/main.py", "dev",
    )
    assert captured["cwd"] == tmp_path
    assert captured["env"] == {
        "VOICE_QA_MODE": "1", "LIVEKIT_AGENT_NAME": "",
        "DATABASE_URL": "postgres://synthetic", "LIVEKIT_URL": "ws://127.0.0.1:7880",
        "LIVEKIT_API_KEY": "synthetic-key", "LIVEKIT_API_SECRET": "synthetic-secret",
        "VOICE_QA_RECEIPT_FILE": str(owned_receipt),
        "AGENT_LOG_FILE": str(captured["log_dir"] / "agent.log"),
        "STT_URL": "http://127.0.0.1:8923/inference",
    }
    assert service.receipt_path(context) == owned_receipt
    assert service.owns(context, identity)
    service.stop(context, identity)
    assert captured["stopped"] == identity["process"]
    assert (captured["log_dir"] / "agent.log").exists()
    assert json.loads((captured["log_dir"] / "receipt-snapshot.json").read_text())["process"]["pid"] == 777


def test_strict_verifier_stdout_and_owned_pid_binding(monkeypatch, tmp_path):
    receipt = tmp_path / "receipt.json"
    write_receipt(receipt, 42)
    context = FakeContext(tmp_path, {
        verifier_command(FakeContext(tmp_path), receipt):
            result('{"status": "READY", "worker_id": "worker-1"}\n'),
    })
    monkeypatch.setattr(subject, "_agent_processes", lambda _context: {42: "dev"})
    service = subject.QaAgentService(receipt_path=receipt, url_provider=lambda _context: "ws://local")
    assert service.probe(context) == Probe(False, "QA NOT READY: verifier_output_invalid")

    context.responses[verifier_command(context, receipt)] = result(
        '{"status":"READY","worker_id":"worker-1"}\n',
    )
    service._selected_receipt = receipt
    service._process = type("Owned", (), {"_children": {99: object()}})()
    assert service.probe(context) == Probe(False, "QA NOT READY: receipt_pid_mismatch")


def test_qa_process_scan_accepts_framework_python_capitalization(tmp_path):
    from scripts.runtime_control import RuntimeContext
    import subprocess

    class ProcessContext(RuntimeContext):
        def run(self, command, **kwargs):
            assert tuple(command) == ("ps", "-axo", "pid=,command=")
            return subprocess.CompletedProcess(command, 0,
                "51 /Library/Frameworks/Python.app/Contents/MacOS/Python agent/main.py start\n"
                "52 /unrelated/node agent/main.py start\n", "")

    context = ProcessContext(tmp_path, tmp_path / "state", qa_mode=True)
    assert subject._agent_processes(context) == {51: "start", 52: None}
