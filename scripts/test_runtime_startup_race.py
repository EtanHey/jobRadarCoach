import os
from pathlib import Path
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parents[1]
HOLDER = r'''
import fcntl, json, os, pathlib, sys, time
from scripts.runtime_process import process_snapshot
state_dir = pathlib.Path(sys.argv[1]); state_dir.mkdir(parents=True)
lock = (state_dir / "up.lock").open("a+")
fcntl.flock(lock, fcntl.LOCK_EX)
(state_dir / "holder.ready").write_text("ready")
delay = float(sys.argv[2]); time.sleep(delay)
if sys.argv[3] != "unknown":
    state = {"supervisor": process_snapshot(os.getpid()), "qa_mode": False, "services": []}
    (state_dir / "state.json").write_text(json.dumps(state))
time.sleep(2)
'''


def _run_duplicate(tmp_path, *, publish, qa=False):
    state_dir = tmp_path / "state"
    holder = subprocess.Popen([
        sys.executable, "-c", HOLDER, str(state_dir), ".4", "publish" if publish else "unknown",
    ], cwd=ROOT, env={**os.environ, "PYTHONPATH": str(ROOT)})
    try:
        deadline = time.monotonic() + 3
        while not (state_dir / "holder.ready").exists() and time.monotonic() < deadline:
            time.sleep(.02)
        assert (state_dir / "holder.ready").exists()
        command = [str(ROOT / "run"), "up"] + (["--qa"] if qa else [])
        env = {
            **os.environ,
            "PYTHONPATH": str(ROOT),
            "RUN_SUPERVISOR_STATE_DIR": str(state_dir),
            "RUN_SERVICES_MODULE": "test_support.runtime_supervisor_services",
            "TEST_MARKER": str(tmp_path / "unused.pid"),
        }
        return subprocess.run(command, cwd=ROOT, env=env, text=True, capture_output=True, timeout=3)
    finally:
        holder.terminate()
        holder.wait(timeout=3)


def test_duplicate_waits_for_same_mode_initial_state(tmp_path):
    duplicate = _run_duplicate(tmp_path, publish=True)
    assert duplicate.returncode == 0
    assert "already running in requested mode" in duplicate.stdout
    assert "mode differs" not in duplicate.stderr


def test_duplicate_reports_unknown_when_initial_state_never_appears(tmp_path):
    duplicate = _run_duplicate(tmp_path, publish=False, qa=True)
    assert duplicate.returncode == 1
    assert "initialization state unknown" in duplicate.stderr
    assert "mode differs" not in duplicate.stderr
    assert "already running" not in duplicate.stdout
