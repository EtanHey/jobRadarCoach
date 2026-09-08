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
