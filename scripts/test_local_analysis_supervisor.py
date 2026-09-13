from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import pytest

from scripts import local_analysis_supervisor


def read_status(state_dir: Path) -> dict[str, object]:
    return json.loads((state_dir / "status.json").read_text(encoding="utf-8"))


def read_supervisor_events(state_dir: Path) -> list[dict[str, object]]:
    path = next((state_dir / "logs").glob("*.supervisor.jsonl"))
    return [json.loads(line) for line in path.read_text().splitlines()]


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


def test_timeout_before_credential_boundary_records_phase(
    tmp_path: Path, monkeypatch,
) -> None:
    monkeypatch.setattr(local_analysis_supervisor, "TERMINATION_GRACE_SECONDS", 0.1)
    assert local_analysis_supervisor.run_once(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        state_dir=tmp_path,
        timeout_seconds=0.1,
        credential_boundary=True,
        credential_timeout_seconds=0.1,
    ) == 124

    status = read_status(tmp_path)
    assert status["phase"] == "credential_acquisition"
    assert isinstance(status["run_id"], str)
    events = read_supervisor_events(tmp_path)
    assert [event["outcome"] for event in events] == ["started", "timed_out"]
    assert {event["run_id"] for event in events} == {status["run_id"]}


def test_credential_timeout_is_independent_of_analysis_budget(
    tmp_path: Path, monkeypatch,
) -> None:
    monkeypatch.setattr(local_analysis_supervisor, "TERMINATION_GRACE_SECONDS", 0.1)
    started = time.monotonic()
    assert local_analysis_supervisor.run_once(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        state_dir=tmp_path,
        timeout_seconds=5,
        credential_boundary=True,
        credential_timeout_seconds=0.1,
    ) == 124
    assert time.monotonic() - started < 1
    assert read_status(tmp_path)["phase"] == "credential_acquisition"


def test_credential_boundary_is_durable_before_worker_exec(tmp_path: Path) -> None:
    command = [
        sys.executable,
        "-m",
        "scripts.local_analysis_supervisor",
        "--credential-ready-child",
        "--",
        sys.executable,
        "-c",
        "print('worker-ran')",
    ]
    assert local_analysis_supervisor.run_once(
        command, state_dir=tmp_path, timeout_seconds=5, credential_boundary=True,
    ) == 0

    status = read_status(tmp_path)
    assert status["phase"] == "analysis"
    events = read_supervisor_events(tmp_path)
    assert [event["outcome"] for event in events] == [
        "started", "credential_acquired", "succeeded",
    ]
    assert set(events[1]) == {"at", "event", "outcome", "phase", "run_id"}
    assert {event["run_id"] for event in events} == {status["run_id"]}


def test_analysis_gets_full_budget_after_credential_boundary(tmp_path: Path) -> None:
    command = [
        sys.executable,
        "-m",
        "scripts.local_analysis_supervisor",
        "--credential-ready-child",
        "--",
        sys.executable,
        "-c",
        "import time; time.sleep(0.2)",
    ]
    assert local_analysis_supervisor.run_once(
        command,
        state_dir=tmp_path,
        timeout_seconds=0.5,
        credential_boundary=True,
        credential_timeout_seconds=0.1,
    ) == 0
    assert read_status(tmp_path)["phase"] == "analysis"


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


@pytest.mark.parametrize("interrupt", [signal.SIGTERM, signal.SIGINT])
def test_signal_records_interruption_and_kills_stubborn_process_group(
    tmp_path: Path, interrupt: signal.Signals,
) -> None:
    state_dir = tmp_path / interrupt.name
    ready = tmp_path / f"{interrupt.name}-ready"
    survived = tmp_path / f"{interrupt.name}-survived"
    grandchild = (
        "import signal,time,pathlib; "
        "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
        "signal.signal(signal.SIGINT, signal.SIG_IGN); "
        f"pathlib.Path({str(ready)!r}).write_text('ready'); "
        f"time.sleep(0.8); pathlib.Path({str(survived)!r}).write_text('alive')"
    )
    child = (
        "import signal,subprocess,sys,time; "
        "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
        "signal.signal(signal.SIGINT, signal.SIG_IGN); "
        f"subprocess.Popen([sys.executable, '-c', {grandchild!r}]); "
        "time.sleep(30)"
    )
    runner = (
        "from pathlib import Path; import sys; "
        "from scripts import local_analysis_supervisor as supervisor; "
        "supervisor.TERMINATION_GRACE_SECONDS = 0.1; "
        f"raise SystemExit(supervisor.run_once([sys.executable, '-c', {child!r}], "
        "state_dir=Path(sys.argv[1]), timeout_seconds=30))"
    )
    supervisor = subprocess.Popen(
        [sys.executable, "-c", runner, str(state_dir)],
        cwd=Path(__file__).parents[1],
    )
    deadline = time.monotonic() + 3
    while not ready.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert ready.exists()

    os.kill(supervisor.pid, interrupt)
    assert supervisor.wait(timeout=5) == 128 + interrupt
    status = read_status(state_dir)
    assert status["outcome"] == "interrupted"
    assert status["exit_code"] == 128 + interrupt
    assert status["signal"] == interrupt.name
    time.sleep(0.9)
    assert not survived.exists()


@pytest.mark.parametrize("value", ["nan", "inf", "-inf"])
def test_environment_refuses_nonfinite_timeout(monkeypatch, value: str) -> None:
    monkeypatch.setenv("JRC_LOCAL_ANALYSIS_ENV_FILE", "/tmp/reference-only.env")
    monkeypatch.setenv("JRC_LOCAL_ANALYSIS_RUN_TIMEOUT_SECONDS", value)

    with pytest.raises(ValueError, match="finite"):
        local_analysis_supervisor._command_from_environment()


def test_environment_wraps_worker_with_credential_boundary(monkeypatch) -> None:
    monkeypatch.setenv("JRC_LOCAL_ANALYSIS_ENV_FILE", "/tmp/reference-only.env")
    command, _state_dir, _analysis_timeout, _credential_timeout = (
        local_analysis_supervisor._command_from_environment()
    )

    boundary = command.index("--credential-ready-child")
    assert command[boundary - 2:boundary] == ["-m", "scripts.local_analysis_supervisor"]
    assert command[boundary + 1] == "--"
    assert command[boundary + 2:boundary + 5] == [
        sys.executable, "-m", "scripts.local_analysis",
    ]


def test_environment_uses_separate_conservative_phase_budgets(monkeypatch) -> None:
    monkeypatch.setenv("JRC_LOCAL_ANALYSIS_ENV_FILE", "/tmp/reference-only.env")
    monkeypatch.delenv("JRC_LOCAL_ANALYSIS_RUN_TIMEOUT_SECONDS", raising=False)
    monkeypatch.delenv("JRC_LOCAL_ANALYSIS_CREDENTIAL_TIMEOUT_SECONDS", raising=False)

    _command, _state_dir, analysis_timeout, credential_timeout = (
        local_analysis_supervisor._command_from_environment()
    )
    assert analysis_timeout == 1620
    assert credential_timeout == 60
    assert analysis_timeout >= 6 * 2 * 120 + 180


def test_environment_refuses_inadequate_custom_analysis_budget(monkeypatch) -> None:
    monkeypatch.setenv("JRC_LOCAL_ANALYSIS_ENV_FILE", "/tmp/reference-only.env")
    monkeypatch.setenv("JRC_LOCAL_ANALYSIS_MAX_ITEMS", "6")
    monkeypatch.setenv("JRC_LOCAL_ANALYSIS_TIMEOUT_SECONDS", "120")
    monkeypatch.setenv("JRC_LOCAL_ANALYSIS_RUN_TIMEOUT_SECONDS", "840")

    with pytest.raises(ValueError, match="at least 1620"):
        local_analysis_supervisor._command_from_environment()


def test_environment_derives_budget_from_custom_workload(monkeypatch) -> None:
    monkeypatch.setenv("JRC_LOCAL_ANALYSIS_ENV_FILE", "/tmp/reference-only.env")
    monkeypatch.setenv("JRC_LOCAL_ANALYSIS_MAX_ITEMS", "3")
    monkeypatch.setenv("JRC_LOCAL_ANALYSIS_TIMEOUT_SECONDS", "10")
    monkeypatch.delenv("JRC_LOCAL_ANALYSIS_RUN_TIMEOUT_SECONDS", raising=False)

    command, _state_dir, analysis_timeout, _credential_timeout = (
        local_analysis_supervisor._command_from_environment()
    )
    assert analysis_timeout == 240
    assert command[command.index("--max-items") + 1] == "3"
    assert command[command.index("--timeout-seconds") + 1] == "10"


def test_credential_child_missing_phase_environment_is_configuration_error(
    monkeypatch, capsys,
) -> None:
    monkeypatch.delenv("JRC_LOCAL_ANALYSIS_STATE_DIR", raising=False)
    monkeypatch.delenv("JRC_LOCAL_ANALYSIS_SUPERVISOR_LOG", raising=False)
    monkeypatch.setenv("JRC_LOCAL_ANALYSIS_RUN_ID", "00000000-0000-0000-0000-000000000001")

    assert local_analysis_supervisor.main(
        ["--credential-ready-child", "--", sys.executable, "-c", "pass"]
    ) == 2
    assert json.loads(capsys.readouterr().err)["outcome"] == "configuration_error"


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_run_once_refuses_nonfinite_timeout(tmp_path: Path, value: float) -> None:
    with pytest.raises(ValueError, match="finite"):
        local_analysis_supervisor.run_once(
            [sys.executable, "-c", "raise SystemExit(99)"],
            state_dir=tmp_path,
            timeout_seconds=value,
        )


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
