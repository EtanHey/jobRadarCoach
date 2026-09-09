import json
import sys

from scripts.runtime_process import ProcessService, Probe, RuntimeContext
from scripts.runtime_diagnostics import create_run_logs


def test_crash_output_and_exit_survive_teardown_and_next_run(tmp_path):
    context = RuntimeContext(tmp_path, tmp_path / ".run-state")
    context.state_dir.mkdir()
    logs = create_run_logs(context, "room-agent")
    ready = tmp_path / "ready"
    service = ProcessService("room-agent", (sys.executable, "-u", "-c",
        "import pathlib,sys,time; pathlib.Path(sys.argv[1]).touch(); "
        "print('fatal worker diagnostic', file=sys.stderr); time.sleep(.3); sys.exit(23)", str(ready)),
        lambda _: Probe(ready.exists()), log_dir=logs, readiness_interval=.01)
    identity = service.start(context)
    service._children[identity["pid"]].wait(timeout=5)
    service.stop(context, identity)
    context.state_dir.rmdir()
    assert "fatal worker diagnostic" in (logs / "console.log").read_text()
    events = [json.loads(line) for line in (logs / "events.jsonl").read_text().splitlines()]
    assert events[-1]["exit_code"] == 23
    assert events[-1]["event"] == "stopped"
    assert logs != create_run_logs(context, "room-agent")
    assert (logs / "console.log").stat().st_mode & 0o777 == 0o600


def test_startup_failure_preserves_traceback_and_reaps_process(tmp_path):
    context = RuntimeContext(tmp_path, tmp_path / ".run-state", qa_mode=True)
    logs = create_run_logs(context, "qa-agent")
    service = ProcessService("qa-agent", (sys.executable, "-c", "raise RuntimeError('startup proof')"),
        lambda _: Probe(False), log_dir=logs, readiness_interval=.01)
    try:
        service.start(context)
    except RuntimeError:
        pass
    else:
        raise AssertionError("crash was accepted as ready")
    assert all(child.poll() is not None for child in service._children.values())
    assert "RuntimeError: startup proof" in (logs / "console.log").read_text()
    assert json.loads((logs / "events.jsonl").read_text().splitlines()[-1])["event"] == "startup_failed"


def test_snapshot_io_error_preserves_original_receipt(monkeypatch, tmp_path, capsys):
    import scripts.runtime_diagnostics as diagnostics
    context = RuntimeContext(tmp_path, tmp_path / ".run-state")
    logs = create_run_logs(context, "room-agent")
    receipt = tmp_path / "receipt.json"
    receipt.write_text('{"process":{"pid":123}}')
    def full_disk(_path):
        raise OSError("disk full")
    monkeypatch.setattr(diagnostics, "private_append", full_disk)
    assert diagnostics.retain_receipt(context, logs, receipt) is False
    assert receipt.read_text() == '{"process":{"pid":123}}'
    assert "original retained" in capsys.readouterr().err


def test_failed_termination_snapshots_both_modes_without_deleting_live_receipt(monkeypatch, tmp_path):
    import pytest
    from scripts.runtime_room_agent import RoomAgentService
    from scripts.runtime_qa_agent import QaAgentService
    for service in (RoomAgentService(), QaAgentService()):
        context = RuntimeContext(tmp_path, tmp_path / service.name)
        context.state_dir.mkdir()
        receipt = service._owned_path(context)
        receipt.write_text('{"process":{"pid":123}}')
        logs = create_run_logs(context, service.name)
        class FailedStop:
            def stop(self, *_args):
                raise RuntimeError("owned group did not exit")
        service._process = FailedStop()
        monkeypatch.setattr(service, "owns", lambda *_: True)
        with pytest.raises(RuntimeError, match="owned group did not exit"):
            service.stop(context, {"process": {"pid": 123}, "log_dir": str(logs)})
        assert receipt.exists()
        assert (logs / "receipt-snapshot.json").read_text() == receipt.read_text()
