import json
import os
import signal
import subprocess
import sys

from scripts.runtime_control import PartialStartError, Probe, RuntimeContext, Supervisor
from test_support.runtime_cli_support import ROOT, finish, is_alive, launch_up, run_entry, wait_for
from test_support.runtime_supervisor_services import WORKER


def test_borrowed_process_is_untouched(tmp_path):
    owner = None
    marker = tmp_path / "worker.pid"
    borrowed = subprocess.Popen([sys.executable, "-c", WORKER, str(marker)])
    try:
        wait_for(marker.exists)
        owner, env = launch_up(tmp_path)
        state = tmp_path / "state/state.json"
        wait_for(lambda: state.exists() and '"mode": "borrowed"' in state.read_text())
        owner.send_signal(2)
        output = owner.communicate(timeout=5)[0]
        assert "tiny: borrowed" in output and borrowed.poll() is None
    finally:
        if owner is not None:
            finish(owner)
        borrowed.terminate()
        borrowed.wait(timeout=3)


def test_status_fails_closed_during_qa_health_threshold_window(tmp_path, capsys):
    class UnreadyBorrowed:
        name = "qa-verifier"

        def probe(self, _context):
            return Probe(False, "QA receipt is NOT_READY")

    context = RuntimeContext(ROOT, tmp_path / "state", qa_mode=True)
    supervisor = Supervisor(context, [UnreadyBorrowed()])
    supervisor._write_state([{"name": "qa-verifier", "mode": "borrowed"}])

    assert supervisor.status() == 1
    output = capsys.readouterr().out
    assert "supervisor: checking mode=QA" in output
    assert "qa-verifier: borrowed checking (QA receipt is NOT_READY)" in output


def test_repeated_borrowed_failure_degrades_without_killing_owned_child_and_recovers(tmp_path):
    health = tmp_path / "kokoro.health"
    health.write_text("healthy")
    owner, env = launch_up(tmp_path, "health-policy")
    marker = tmp_path / "worker.pid"
    state = tmp_path / "state/state.json"
    try:
        wait_for(
            lambda: marker.exists() and state.exists() and '"mode": "owned"' in state.read_text()
        )
        child_pid = int(marker.read_text())

        health.write_text("failed")
        wait_for(
            lambda: '"kokoro": {"condition": "readiness_failed", '
            '"reason": "synthetic Kokoro timeout"}' in state.read_text()
        )
        degraded = run_entry(ROOT / "run", env, "status")
        assert owner.poll() is None and is_alive(child_pid)
        assert degraded.returncode == 1
        assert "supervisor: degraded mode=normal" in degraded.stdout
        assert "kokoro: borrowed degraded (synthetic Kokoro timeout)" in degraded.stdout

        health.write_text("healthy")
        wait_for(lambda: '"degraded": {}' in state.read_text())
        recovered = run_entry(ROOT / "run", env, "status")
        assert recovered.returncode == 0
        assert "supervisor: running mode=normal" in recovered.stdout
        assert owner.poll() is None and is_alive(child_pid)

        owner.send_signal(2)
        output = owner.communicate(timeout=5)[0]
        assert owner.returncode == 0 and "tiny: stopped" in output
        events_path, = (tmp_path / ".run-logs").glob("*-supervisor-*/events.jsonl")
        events = [json.loads(line) for line in events_path.read_text().splitlines()]
        assert [event["event"] for event in events] == ["started", "degraded", "recovered", "shutdown"]
        assert events[0]["qa_mode"] is False
        assert events[1]["affected_service"] == "kokoro"
        assert events[1]["mode"] == "borrowed"
        assert events[1]["condition"] == "readiness_failed"
        assert events[1]["consecutive_failures"] >= 3
        assert events[-1]["reason"] == "signal:SIGINT"
        assert not state.exists()
    finally:
        finish(owner)


def test_owned_failure_does_not_tear_down_unrelated_owned_process(tmp_path):
    health = tmp_path / "owned.health"
    health.write_text("healthy")
    owner, env = launch_up(tmp_path, "owned-health-policy")
    failed_marker = tmp_path / "worker.pid"
    unrelated_marker = tmp_path / "unrelated.pid"
    state = tmp_path / "state/state.json"
    try:
        wait_for(
            lambda: failed_marker.exists() and unrelated_marker.exists()
            and state.exists() and state.read_text().count('"mode": "owned"') == 2
        )
        failed_pid = int(failed_marker.read_text())
        unrelated_pid = int(unrelated_marker.read_text())

        health.write_text("failed")
        wait_for(
            lambda: '"flappable": {"condition": "readiness_failed", '
            '"reason": "synthetic owned timeout"}' in state.read_text()
        )
        status = run_entry(ROOT / "run", env, "status")
        assert status.returncode == 1
        assert "flappable: owned degraded (synthetic owned timeout)" in status.stdout
        assert owner.poll() is None
        assert is_alive(failed_pid) and is_alive(unrelated_pid)

        health.write_text("healthy")
        wait_for(lambda: '"degraded": {}' in state.read_text())
        os.kill(failed_pid, signal.SIGTERM)
        wait_for(lambda: not failed_marker.exists())
        wait_for(
            lambda: '"flappable": {"condition": "stopped", '
            '"reason": "synthetic owned timeout"}' in state.read_text()
        )
        stopped = run_entry(ROOT / "run", env, "status")
        assert stopped.returncode == 1
        assert "flappable: owned stopped/degraded (synthetic owned timeout)" in stopped.stdout
        assert owner.poll() is None and is_alive(unrelated_pid)

        owner.send_signal(2)
        output = owner.communicate(timeout=5)[0]
        assert owner.returncode == 0
        assert "unrelated: stopped" in output and "flappable: stopped" in output
        assert not is_alive(failed_pid) and not is_alive(unrelated_pid)
    finally:
        finish(owner)


def test_failed_startup_rolls_back_prior_process(tmp_path):
    owner, env = launch_up(tmp_path, "rollback")
    marker = tmp_path / "worker.pid"
    output = owner.communicate(timeout=5)[0]
    assert owner.returncode == 1
    assert "startup failed: exited during startup (7)" in output
    wait_for(lambda: not marker.exists())
    assert "first: stopped" in output


def test_control_c_interrupts_readiness_wait(tmp_path):
    owner, env = launch_up(tmp_path, "interrupt")
    marker = tmp_path / "worker.pid"
    try:
        wait_for(marker.exists)
        pid = int(marker.read_text())
        owner.send_signal(2)
        output = owner.communicate(timeout=5)[0]
        assert owner.returncode == 0 and "startup interrupted" in output
        assert not is_alive(pid)
    finally:
        finish(owner)


def test_down_reports_and_preserves_cleanup_failure(tmp_path):
    owner, env = launch_up(tmp_path, "cleanup-fail")
    state = tmp_path / "state/state.json"
    try:
        wait_for(lambda: state.exists() and '"mode": "owned"' in state.read_text())
        down = run_entry(ROOT / "run", env, "down")
        owner.communicate(timeout=5)
        assert down.returncode == owner.returncode == 1
        assert "synthetic stop failure" in down.stderr
        retained = state.read_text()
        assert "cleanup_failures" in retained
        failed_status = run_entry(ROOT / "run", env, "status")
        assert "stopped mode=normal (cleanup failed:" in failed_status.stdout
        again = run_entry(ROOT / "run", env, "up")
        assert again.returncode == 1 and "refusing up" in again.stderr
        assert state.read_text() == retained
    finally:
        finish(owner)


def test_partial_start_ownership_is_persisted_when_rollback_fails(tmp_path):
    class PartialService:
        name = "partial"
        def probe(self, _context): return Probe(False)
        def start(self, _context): raise PartialStartError("partial apply", {"key": "created"})
        def owns(self, _context, identity): return identity == {"key": "created"}
        def stop(self, _context, _identity): raise RuntimeError("rollback unconfirmed")

    context = RuntimeContext(ROOT, tmp_path / "state")
    assert Supervisor(context, [PartialService()]).up() == 1
    retained = (context.state_dir / "state.json").read_text()
    assert '"key": "created"' in retained and "rollback unconfirmed" in retained


def test_qa_mode_and_symlinked_jrc_are_visible_and_guarded(tmp_path):
    owner, env = launch_up(tmp_path, qa=True)
    state = tmp_path / "state/state.json"
    try:
        wait_for(lambda: state.exists() and '"mode": "owned"' in state.read_text())
        symlink = tmp_path / "jrc"
        symlink.symlink_to(ROOT / "jrc")
        status = run_entry(symlink, env, "status")
        normal_up = run_entry(ROOT / "run", env, "up")
        qa_up = run_entry(symlink, env, "run", "--qa")
        assert '"qa_mode": true' in state.read_text()
        assert status.returncode == 0 and "mode=QA" in status.stdout
        unavailable_env = {**env, "RUN_SERVICES_MODULE": "missing_test_adapter"}
        unavailable = run_entry(ROOT / "run", unavailable_env, "status")
        assert unavailable.returncode == 2 and "running mode=QA" in unavailable.stdout
        assert "configuration error:" in unavailable.stderr and "Traceback" not in unavailable.stderr
        assert normal_up.returncode == 1 and "run './run down'" in normal_up.stderr
        assert qa_up.returncode == 0 and "requested mode" in qa_up.stdout
        down = run_entry(symlink, env, "down")
        output = owner.communicate(timeout=5)[0]
        assert down.returncode == owner.returncode == 0
        assert "READ-ONLY QA MODE REQUESTED" in output
    finally:
        finish(owner)
