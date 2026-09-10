from __future__ import annotations

import fcntl
import json
from pathlib import Path
import subprocess
import sys
import time

from scripts import local_analysis_supervisor


def read_status(state_dir: Path) -> dict[str, object]:
    return json.loads((state_dir / "status.json").read_text(encoding="utf-8"))


def test_failed_run_records_status_and_does_not_block_next_cycle(tmp_path: Path) -> None:
    assert local_analysis_supervisor.run_once(
        [sys.executable, "-c", "raise SystemExit(7)"],
        state_dir=tmp_path,
        timeout_seconds=5,
    ) == 7
    assert read_status(tmp_path)["outcome"] == "failed"

    assert local_analysis_supervisor.run_once(
        [sys.executable, "-c", "print('future-cycle-ran')"],
        state_dir=tmp_path,
        timeout_seconds=5,
    ) == 0
    status = read_status(tmp_path)
    assert status["outcome"] == "succeeded"
    assert status["exit_code"] == 0
    assert (tmp_path / "status.json").stat().st_mode & 0o777 == 0o600
    output = next(
        path for path in (tmp_path / "logs").glob("*.jsonl")
        if not path.name.endswith(".supervisor.jsonl")
    )
    assert "future-cycle-ran" in output.read_text(encoding="utf-8")


def test_timeout_is_bounded_and_recorded(tmp_path: Path) -> None:
    started = time.monotonic()
    result = local_analysis_supervisor.run_once(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        state_dir=tmp_path,
        timeout_seconds=0.1,
    )
    assert result == 124
    assert time.monotonic() - started < 5
    assert read_status(tmp_path)["outcome"] == "timed_out"


def test_timeout_kills_child_that_ignores_sigterm(
    tmp_path: Path, monkeypatch,
) -> None:
    monkeypatch.setattr(local_analysis_supervisor, "TERMINATION_GRACE_SECONDS", 0.1)
    ready = tmp_path / "child-ready"
    marker = tmp_path / "child-survived"
    child = (
        "import signal,time,pathlib; "
        "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
        f"pathlib.Path({str(ready)!r}).write_text('ready'); "
        f"time.sleep(0.4); pathlib.Path({str(marker)!r}).write_text('alive')"
    )
    parent = (
        "import subprocess,sys,time; "
        f"subprocess.Popen([sys.executable, '-c', {child!r}]); "
        "time.sleep(30)"
    )
    process = subprocess.Popen([sys.executable, "-c", parent], start_new_session=True)
    deadline = time.monotonic() + 2
    while not ready.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert ready.exists()

    local_analysis_supervisor._terminate_process_group(process)
    time.sleep(0.5)
    assert not marker.exists()


def test_outer_lock_prevents_overlapping_secret_resolution(tmp_path: Path) -> None:
    tmp_path.mkdir(parents=True, exist_ok=True)
    with (tmp_path / "scheduler.lock").open("a", encoding="utf-8") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert local_analysis_supervisor.run_once(
            [sys.executable, "-c", "raise SystemExit(99)"],
            state_dir=tmp_path,
            timeout_seconds=5,
        ) == 0
    log = next((tmp_path / "logs").glob("*.supervisor.jsonl")).read_text(
        encoding="utf-8"
    )
    assert '"outcome":"already_running"' in log


def test_launcher_uses_supervisor_before_op_run() -> None:
    launcher = (Path(__file__).parent / "run_local_analysis.sh").read_text()
    assert "scripts.local_analysis_supervisor" in launcher
    assert '"${op_cli}" run' not in launcher
