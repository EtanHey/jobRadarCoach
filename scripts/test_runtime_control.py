from pathlib import Path
import signal
import stat

from test_support.runtime_cli_support import ROOT, finish, is_alive, launch_up, run_entry, wait_for


def test_up_status_concurrent_up_and_down_manage_real_process(tmp_path):
    owner, env = launch_up(tmp_path)
    marker = Path(env["TEST_MARKER"])
    state = tmp_path / "state/state.json"
    try:
        wait_for(lambda: marker.exists() and state.exists() and '"mode": "owned"' in state.read_text())
        pid = int(marker.read_text())
        assert stat.S_IMODE(state.parent.stat().st_mode) == 0o700
        assert stat.S_IMODE(state.stat().st_mode) == 0o600
        status = run_entry(ROOT / "run", env, "status")
        duplicate = run_entry(ROOT / "run", env, "up")
        down = run_entry(ROOT / "run", env, "down")
        output = owner.communicate(timeout=5)[0]
        assert status.returncode == 0 and "tiny: owned" in status.stdout
        assert duplicate.returncode == 0 and "already running" in duplicate.stdout
        assert down.returncode == owner.returncode == 0
        assert "tiny: stopped" in output and not is_alive(pid)
        assert not state.exists()
        stopped = run_entry(ROOT / "run", env, "status")
        assert stopped.returncode == 1 and "mode=unknown" in stopped.stdout
    finally:
        finish(owner)


def test_control_c_stops_owned_process(tmp_path):
    owner, env = launch_up(tmp_path)
    marker = Path(env["TEST_MARKER"])
    state = tmp_path / "state/state.json"
    try:
        wait_for(lambda: marker.exists() and state.exists() and '"mode": "owned"' in state.read_text())
        pid = int(marker.read_text())
        owner.send_signal(signal.SIGINT)
        output = owner.communicate(timeout=5)[0]
        assert owner.returncode == 0 and "tiny: stopped" in output
        assert not is_alive(pid)
    finally:
        finish(owner)
