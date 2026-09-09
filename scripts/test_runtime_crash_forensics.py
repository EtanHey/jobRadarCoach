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
