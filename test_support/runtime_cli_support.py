"""CLI helpers for disposable run-supervisor subprocess tests."""

import os
from pathlib import Path
import signal
import subprocess
import time


ROOT = Path(__file__).resolve().parents[1]


def wait_for(condition, timeout=4):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return
        time.sleep(.03)
    raise AssertionError("condition did not become true")


def is_alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


def environment(tmp_path, mode="normal"):
    return {
        **os.environ,
        "PYTHONPATH": str(ROOT),
        "RUN_SERVICES_MODULE": "test_support.runtime_supervisor_services",
        "RUN_SUPERVISOR_STATE_DIR": str(tmp_path / "state"),
        "TEST_MARKER": str(tmp_path / "worker.pid"),
        "TEST_MODE": mode,
        "RUN_HEALTH_INTERVAL": ".05",
    }


def launch_up(tmp_path, mode="normal", qa=False):
    env = environment(tmp_path, mode)
    command = [str(ROOT / ("jrc" if qa else "run")), "run" if qa else "up"]
    if qa:
        command.append("--qa")
    process = subprocess.Popen(
        command, cwd=ROOT, env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    return process, env


def run_entry(executable, env, *arguments):
    return subprocess.run(
        [str(executable), *arguments], cwd=ROOT, env=env,
        text=True, capture_output=True, check=False, timeout=5,
    )


def finish(process):
    if process.poll() is None:
        process.send_signal(signal.SIGTERM)
    return process.communicate(timeout=5)[0]
