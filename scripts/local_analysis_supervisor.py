#!/usr/bin/env python3
"""Run one local-analysis cycle with outer locking, timeout, logs, and status."""

from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone

TERMINATION_GRACE_SECONDS = 2.0


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
) -> int:
    """Run ``command`` once without overlap and persist a sanitized outcome."""

    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
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
        status: dict[str, object] = {
            "started_at": started_at,
            "finished_at": None,
            "outcome": "running",
            "exit_code": None,
        }
        _write_status(status_path, status)
        exit_code = 127
        outcome = "launch_error"
        failure: str | None = None
        with output_path.open("ab") as output, error_path.open("ab") as error:
            try:
                process = subprocess.Popen(
                    command,
                    stdin=subprocess.DEVNULL,
                    stdout=output,
                    stderr=error,
                    start_new_session=True,
                )
            except OSError as exception:
                failure = type(exception).__name__
            else:
                try:
                    exit_code = process.wait(timeout=timeout_seconds)
                except subprocess.TimeoutExpired:
                    _terminate_process_group(process)
                    exit_code = 124
                    outcome = "timed_out"
                else:
                    outcome = "succeeded" if exit_code == 0 else "failed"

        finished_at = _now()
        event: dict[str, object] = {
            "event": "supervisor",
            "at": finished_at,
            "outcome": outcome,
            "exit_code": exit_code,
        }
        if failure:
            event["failure"] = failure
        _append_event(supervisor_path, **event)
        status.update(event)
        status["finished_at"] = finished_at
        status.pop("event")
        _write_status(status_path, status)
        return exit_code


def _command_from_environment() -> tuple[list[str], Path, float]:
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
    timeout_seconds = float(os.environ.get("JRC_LOCAL_ANALYSIS_RUN_TIMEOUT_SECONDS", "840"))
    if timeout_seconds > 3600:
        raise ValueError("JRC_LOCAL_ANALYSIS_RUN_TIMEOUT_SECONDS must be at most 3600")
    command = [
        op_cli,
        "run",
        "--env-file",
        env_file,
        "--",
        analysis_python,
        "-m",
        "scripts.local_analysis",
        "--max-items",
        os.environ.get("JRC_LOCAL_ANALYSIS_MAX_ITEMS", "6"),
        "--timeout-seconds",
        os.environ.get("JRC_LOCAL_ANALYSIS_TIMEOUT_SECONDS", "120"),
        "--lease-seconds",
        os.environ.get("JRC_LOCAL_ANALYSIS_LEASE_SECONDS", "900"),
        "--lock-file",
        str(state_dir / "worker.lock"),
    ]
    return command, state_dir, timeout_seconds


def main() -> int:
    try:
        command, state_dir, timeout_seconds = _command_from_environment()
        return run_once(command, state_dir=state_dir, timeout_seconds=timeout_seconds)
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
