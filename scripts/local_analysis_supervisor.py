#!/usr/bin/env python3
"""Run one local-analysis cycle with outer locking, timeout, logs, and status."""

from __future__ import annotations

import fcntl
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from uuid import UUID, uuid4

TERMINATION_GRACE_SECONDS = 2.0
PHASE_POLL_SECONDS = 0.05
DEFAULT_CREDENTIAL_TIMEOUT_SECONDS = 60.0
ANALYSIS_OVERHEAD_SECONDS = 180.0
MAX_MODEL_ATTEMPTS_PER_ITEM = 2
MAX_CREDENTIAL_TIMEOUT_SECONDS = 300.0
MAX_ANALYSIS_TIMEOUT_SECONDS = 10_800.0


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _write_status(path: Path, status: dict[str, object]) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(
            json.dumps(status, separators=(",", ":"), sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary.chmod(0o600)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _append_event(path: Path, **fields: object) -> None:
    with path.open("a", encoding="utf-8") as output:
        output.write(json.dumps(fields, separators=(",", ":"), sort_keys=True) + "\n")


def _phase_reached(path: Path, run_id: str, phase: str) -> bool:
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("run_id") == run_id and event.get("phase") == phase:
            return True
    return False


def _credential_ready_child(command: list[str]) -> int:
    if not command:
        raise ValueError("credential-ready child command is required")
    run_id = os.environ.get("JRC_LOCAL_ANALYSIS_RUN_ID", "").strip()
    if not run_id or str(UUID(run_id)) != run_id:
        raise ValueError("JRC_LOCAL_ANALYSIS_RUN_ID must be a canonical UUID")
    state_dir_value = os.environ.get("JRC_LOCAL_ANALYSIS_STATE_DIR", "").strip()
    supervisor_value = os.environ.get("JRC_LOCAL_ANALYSIS_SUPERVISOR_LOG", "").strip()
    if not state_dir_value or not supervisor_value:
        raise ValueError(
            "JRC_LOCAL_ANALYSIS_STATE_DIR and JRC_LOCAL_ANALYSIS_SUPERVISOR_LOG "
            "are required"
        )
    state_dir = Path(state_dir_value)
    supervisor_path = Path(supervisor_value)
    if supervisor_path.parent != state_dir / "logs":
        raise ValueError("supervisor log must be inside the local-analysis log directory")
    _append_event(
        supervisor_path,
        event="supervisor",
        at=_now(),
        outcome="credential_acquired",
        phase="analysis",
        run_id=run_id,
    )
    os.execvp(command[0], command)
    return 127


def _terminate_process_group(process: subprocess.Popen[bytes]) -> None:
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        process.wait()
        return
    deadline = time.monotonic() + TERMINATION_GRACE_SECONDS
    try:
        process.wait(timeout=TERMINATION_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        pass
    remaining = deadline - time.monotonic()
    if remaining > 0:
        time.sleep(remaining)
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait()


def run_once(
    command: list[str],
    *,
    state_dir: Path,
    timeout_seconds: float,
    credential_boundary: bool = False,
    credential_timeout_seconds: float = DEFAULT_CREDENTIAL_TIMEOUT_SECONDS,
) -> int:
    """Run ``command`` once without overlap and persist a sanitized outcome."""

    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be finite and positive")
    if (
        not math.isfinite(credential_timeout_seconds)
        or not 0 < credential_timeout_seconds <= MAX_CREDENTIAL_TIMEOUT_SECONDS
    ):
        raise ValueError(
            "credential_timeout_seconds must be finite and between 0 and 300"
        )
    os.umask(0o077)
    state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    logs_dir = state_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    date = datetime.now(timezone.utc).date().isoformat()
    output_path = logs_dir / f"{date}.jsonl"
    error_path = logs_dir / f"{date}.stderr.log"
    supervisor_path = logs_dir / f"{date}.supervisor.jsonl"
    status_path = state_dir / "status.json"

    with (state_dir / "scheduler.lock").open("a", encoding="utf-8") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            _append_event(
                supervisor_path,
                event="supervisor",
                at=_now(),
                outcome="already_running",
            )
            return 0

        started_at = _now()
        run_id = str(uuid4())
        phase = "credential_acquisition" if credential_boundary else "process"
        status: dict[str, object] = {
            "started_at": started_at,
            "finished_at": None,
            "outcome": "running",
            "exit_code": None,
            "phase": phase,
            "run_id": run_id,
        }
        exit_code = 127
        outcome = "launch_error"
        failure: str | None = None
        interrupted_signum: int | None = None
        process: subprocess.Popen[bytes] | None = None
        handled_signals = (signal.SIGTERM, signal.SIGINT)

        def handle_interrupt(signum: int, _frame: object) -> None:
            nonlocal interrupted_signum
            if interrupted_signum is not None:
                return
            interrupted_signum = signum
            for handled_signal in handled_signals:
                signal.signal(handled_signal, signal.SIG_IGN)
            if process is not None:
                _terminate_process_group(process)

        previous_handlers = {
            handled_signal: signal.getsignal(handled_signal)
            for handled_signal in handled_signals
        }
        for handled_signal in handled_signals:
            signal.signal(handled_signal, handle_interrupt)
        try:
            try:
                _write_status(status_path, status)
                _append_event(
                    supervisor_path,
                    event="supervisor",
                    at=started_at,
                    outcome="started",
                    phase=phase,
                    run_id=run_id,
                )
                with output_path.open("ab") as output, error_path.open("ab") as error:
                    child_environment = os.environ.copy()
                    child_environment.update(
                        {
                            "JRC_LOCAL_ANALYSIS_RUN_ID": run_id,
                            "JRC_LOCAL_ANALYSIS_STATE_DIR": str(state_dir),
                            "JRC_LOCAL_ANALYSIS_SUPERVISOR_LOG": str(supervisor_path),
                        }
                    )
                    try:
                        process = subprocess.Popen(
                            command,
                            stdin=subprocess.DEVNULL,
                            stdout=output,
                            stderr=error,
                            start_new_session=True,
                            env=child_environment,
                        )
                    except OSError as exception:
                        failure = type(exception).__name__
                    else:
                        if interrupted_signum is not None:
                            _terminate_process_group(process)
                        else:
                            deadline = time.monotonic() + (
                                credential_timeout_seconds
                                if credential_boundary
                                else timeout_seconds
                            )
                            while True:
                                if (
                                    credential_boundary
                                    and phase == "credential_acquisition"
                                    and _phase_reached(supervisor_path, run_id, "analysis")
                                ):
                                    phase = "analysis"
                                    deadline = time.monotonic() + timeout_seconds
                                remaining = deadline - time.monotonic()
                                if remaining <= 0:
                                    _terminate_process_group(process)
                                    exit_code = 124
                                    outcome = "timed_out"
                                    break
                                try:
                                    exit_code = process.wait(
                                        timeout=min(PHASE_POLL_SECONDS, remaining)
                                    )
                                except subprocess.TimeoutExpired:
                                    continue
                                outcome = "succeeded" if exit_code == 0 else "failed"
                                break
            finally:
                for handled_signal in handled_signals:
                    signal.signal(handled_signal, signal.SIG_IGN)

            if interrupted_signum is not None:
                if process is not None and process.poll() is None:
                    _terminate_process_group(process)
                exit_code = 128 + interrupted_signum
                outcome = "interrupted"

            if credential_boundary and _phase_reached(
                supervisor_path, run_id, "analysis"
            ):
                phase = "analysis"
            finished_at = _now()
            event: dict[str, object] = {
                "event": "supervisor",
                "at": finished_at,
                "outcome": outcome,
                "exit_code": exit_code,
                "phase": phase,
                "run_id": run_id,
            }
            if failure:
                event["failure"] = failure
            if interrupted_signum is not None:
                event["signal"] = signal.Signals(interrupted_signum).name
            _append_event(supervisor_path, **event)
            status.update(event)
            status["finished_at"] = finished_at
            status.pop("event")
            _write_status(status_path, status)
            return exit_code
        finally:
            for handled_signal, previous_handler in previous_handlers.items():
                signal.signal(handled_signal, previous_handler)


def _command_from_environment() -> tuple[list[str], Path, float, float]:
    env_file = os.environ.get("JRC_LOCAL_ANALYSIS_ENV_FILE", "").strip()
    if not env_file:
        raise ValueError("JRC_LOCAL_ANALYSIS_ENV_FILE is required")
    state_dir = Path(
        os.environ.get(
            "JRC_LOCAL_ANALYSIS_STATE_DIR",
            str(Path.home() / "Library/Application Support/jobRadarCoach/local-analysis"),
        )
    )
    analysis_python = os.environ.get("JRC_LOCAL_ANALYSIS_PYTHON", sys.executable)
    op_cli = os.environ.get("JRC_ONEPASSWORD_CLI", "op")
    max_items = int(os.environ.get("JRC_LOCAL_ANALYSIS_MAX_ITEMS", "6"))
    item_timeout_seconds = float(
        os.environ.get("JRC_LOCAL_ANALYSIS_TIMEOUT_SECONDS", "120")
    )
    if not 1 <= max_items <= 30:
        raise ValueError("JRC_LOCAL_ANALYSIS_MAX_ITEMS must be between 1 and 30")
    if not math.isfinite(item_timeout_seconds) or not 0 < item_timeout_seconds <= 120:
        raise ValueError(
            "JRC_LOCAL_ANALYSIS_TIMEOUT_SECONDS must be finite and between 0 and 120"
        )
    minimum_analysis_timeout = (
        max_items * MAX_MODEL_ATTEMPTS_PER_ITEM * item_timeout_seconds
        + ANALYSIS_OVERHEAD_SECONDS
    )
    configured_analysis_timeout = os.environ.get("JRC_LOCAL_ANALYSIS_RUN_TIMEOUT_SECONDS")
    timeout_seconds = (
        minimum_analysis_timeout
        if configured_analysis_timeout is None
        else float(configured_analysis_timeout)
    )
    if (
        not math.isfinite(timeout_seconds)
        or not 0 < timeout_seconds <= MAX_ANALYSIS_TIMEOUT_SECONDS
    ):
        raise ValueError(
            "JRC_LOCAL_ANALYSIS_RUN_TIMEOUT_SECONDS must be finite and between "
            "0 and 10800"
        )
    if timeout_seconds < minimum_analysis_timeout:
        raise ValueError(
            "JRC_LOCAL_ANALYSIS_RUN_TIMEOUT_SECONDS must be at least "
            f"{minimum_analysis_timeout:g} for the configured item count and item timeout"
        )
    credential_timeout_seconds = float(
        os.environ.get(
            "JRC_LOCAL_ANALYSIS_CREDENTIAL_TIMEOUT_SECONDS",
            str(DEFAULT_CREDENTIAL_TIMEOUT_SECONDS),
        )
    )
    if (
        not math.isfinite(credential_timeout_seconds)
        or not 0 < credential_timeout_seconds <= MAX_CREDENTIAL_TIMEOUT_SECONDS
    ):
        raise ValueError(
            "JRC_LOCAL_ANALYSIS_CREDENTIAL_TIMEOUT_SECONDS must be finite and "
            "between 0 and 300"
        )
    command = [
        op_cli,
        "run",
        "--env-file",
        env_file,
        "--",
        analysis_python,
        "-m",
        "scripts.local_analysis_supervisor",
        "--credential-ready-child",
        "--",
        analysis_python,
        "-m",
        "scripts.local_analysis",
        "--max-items",
        str(max_items),
        "--timeout-seconds",
        f"{item_timeout_seconds:g}",
        "--lease-seconds",
        os.environ.get("JRC_LOCAL_ANALYSIS_LEASE_SECONDS", "900"),
        "--lock-file",
        str(state_dir / "worker.lock"),
    ]
    return command, state_dir, timeout_seconds, credential_timeout_seconds


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    try:
        if arguments[:2] == ["--credential-ready-child", "--"]:
            return _credential_ready_child(arguments[2:])
        if arguments:
            raise ValueError("unsupported supervisor arguments")
        command, state_dir, timeout_seconds, credential_timeout_seconds = (
            _command_from_environment()
        )
        return run_once(
            command,
            state_dir=state_dir,
            timeout_seconds=timeout_seconds,
            credential_boundary=True,
            credential_timeout_seconds=credential_timeout_seconds,
        )
    except (OSError, ValueError) as exception:
        print(
            json.dumps(
                {
                    "event": "supervisor",
                    "outcome": "configuration_error",
                    "failure": type(exception).__name__,
                },
                separators=(",", ":"),
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
