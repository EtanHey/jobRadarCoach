#!/usr/bin/env python3
"""Emit a compact, read-only health receipt for the full-pipeline scheduler."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import stat
import subprocess
from typing import Any, Sequence


LABEL = "com.jobradarcoach.full-pipeline"
DEFAULT_STATE_DIR = Path.home() / "Library/Logs/jobRadarCoach/full-pipeline"
MAX_INPUT_BYTES = 1024 * 1024
LAUNCHCTL = "/bin/launchctl"
LAUNCHCTL_TIMEOUT_SECONDS = 5
LAUNCHCTL_OUTPUT_LIMIT = 64 * 1024
DEFAULT_STALE_AFTER_SECONDS = 7 * 60 * 60
DEFAULT_STALLED_AFTER_SECONDS = 50 * 60
ATTEMPT_FIELDS = (
    "attempt_id",
    "status",
    "started_at",
    "finished_at",
    "run_id",
    "failure",
    "coordinator_failure_stage",
    "coordinator_failure",
)
FAILURE_CODE = re.compile(r"^[A-Za-z][A-Za-z0-9]{0,63}$")
RUN_ID = re.compile(r"^[a-z0-9](?:[-a-z0-9]*[a-z0-9])?$")
ATTEMPT_ID = re.compile(r"^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$")


class StatusInputError(RuntimeError):
    """A scheduler status input is absent, oversized, or invalid."""


def _read_object(path: Path) -> dict[str, Any]:
    try:
        metadata = path.stat()
        if not stat.S_ISREG(metadata.st_mode):
            raise StatusInputError("InputNotRegular")
        if metadata.st_size > MAX_INPUT_BYTES:
            raise StatusInputError("InputTooLarge")
        with path.open("rb") as handle:
            payload = handle.read(MAX_INPUT_BYTES + 1)
        if len(payload) > MAX_INPUT_BYTES:
            raise StatusInputError("InputTooLarge")
        value = json.loads(payload.decode("utf-8"))
    except StatusInputError:
        raise
    except FileNotFoundError as error:
        raise StatusInputError("InputMissing") from error
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise StatusInputError("InputInvalid") from error
    if not isinstance(value, dict):
        raise StatusInputError("InputInvalid")
    return value


def _launchctl(argv: Sequence[str]) -> subprocess.CompletedProcess[bytes] | None:
    try:
        result = subprocess.run(
            [LAUNCHCTL, *argv],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=LAUNCHCTL_TIMEOUT_SECONDS,
            check=False,
            env={"PATH": "/usr/bin:/bin:/usr/sbin:/sbin"},
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if len(result.stdout) > LAUNCHCTL_OUTPUT_LIMIT or len(result.stderr) > LAUNCHCTL_OUTPUT_LIMIT:
        return None
    return result


def probe_launchd() -> str:
    domain = f"gui/{os.getuid()}"
    loaded = _launchctl(["print", f"{domain}/{LABEL}"])
    if loaded is None:
        return "unknown"
    if loaded.returncode:
        return "unloaded"
    disabled = _launchctl(["print-disabled", domain])
    if disabled is None or disabled.returncode:
        return "unknown"
    try:
        rendered = disabled.stdout.decode("utf-8")
    except UnicodeError:
        return "unknown"
    pattern = rf'"{re.escape(LABEL)}"\s*=>\s*(disabled|true)'
    return "disabled" if re.search(pattern, rendered) else "loaded"


def _timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or len(value) > 40:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _matching_string(value: object, pattern: re.Pattern[str]) -> str | None:
    return value if isinstance(value, str) and pattern.fullmatch(value) else None


def _attempt_summary(attempt: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    validators = {
        "attempt_id": ATTEMPT_ID,
        "run_id": RUN_ID,
        "failure": FAILURE_CODE,
        "coordinator_failure_stage": FAILURE_CODE,
        "coordinator_failure": FAILURE_CODE,
    }
    if attempt.get("status") in {"running", "succeeded", "failed"}:
        summary["status"] = attempt["status"]
    for key in ("started_at", "finished_at"):
        if (parsed := _timestamp(attempt.get(key))) is not None:
            summary[key] = parsed.isoformat().replace("+00:00", "Z")
    for key, pattern in validators.items():
        if (value := _matching_string(attempt.get(key), pattern)) is not None:
            summary[key] = value
    return {key: summary[key] for key in ATTEMPT_FIELDS if key in summary}


def _verified_summary(receipt: dict[str, Any]) -> dict[str, Any] | None:
    run_id = _matching_string(receipt.get("run_id"), RUN_ID)
    if run_id is None:
        return None
    summary: dict[str, Any] = {"run_id": run_id}
    for key in ("cohort_count", "new", "extracted", "scored"):
        value = receipt.get(key)
        if type(value) is int and value >= 0:
            summary[key] = value
    failures = receipt.get("failures")
    if isinstance(failures, list):
        summary["failure_count"] = len(failures)
    return summary


def build_status(
    attempt: dict[str, Any],
    receipt: dict[str, Any] | None,
    *,
    now: datetime,
    stale_after_seconds: int = DEFAULT_STALE_AFTER_SECONDS,
    stalled_after_seconds: int = DEFAULT_STALLED_AFTER_SECONDS,
    launchd_state: str = "loaded",
) -> dict[str, Any]:
    status = attempt.get("status")
    started = _timestamp(attempt.get("started_at"))
    finished = _timestamp(attempt.get("finished_at"))
    event_time = finished if status in {"succeeded", "failed"} else started
    age_seconds = None
    timestamp_in_future = False
    if event_time is not None:
        delta_seconds = (now.astimezone(timezone.utc) - event_time).total_seconds()
        timestamp_in_future = delta_seconds < 0
        if not timestamp_in_future:
            age_seconds = int(delta_seconds)

    if launchd_state == "disabled":
        state, reason = "disabled", "LaunchAgentDisabled"
    elif launchd_state == "unloaded":
        state, reason = "unknown", "LaunchAgentUnloaded"
    elif launchd_state != "loaded":
        state, reason = "unknown", "LaunchAgentStateUnknown"
    elif timestamp_in_future:
        state, reason = "unknown", "AttemptTimestampInFuture"
    elif status == "failed":
        state = "failed"
        reason = _matching_string(attempt.get("failure"), FAILURE_CODE)
        reason = reason or "ScheduledAttemptFailed"
    elif status == "running" and (age_seconds is None or age_seconds > stalled_after_seconds):
        state, reason = "stalled", "AttemptExceededRuntimeBound"
    elif status == "running":
        state, reason = "running", None
    elif status == "succeeded" and (age_seconds is None or age_seconds > stale_after_seconds):
        state, reason = "stale", "NoRecentScheduledAttempt"
    elif status == "succeeded":
        state, reason = "healthy", None
    else:
        state, reason = "unknown", "InvalidAttemptStatus"

    result: dict[str, Any] = {
        "schema_version": 1,
        "scheduler": "launchd",
        "label": LABEL,
        "launchd_state": launchd_state,
        "checked_at": now.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "state": state,
        "reason": reason,
        "latest_attempt": _attempt_summary(attempt),
        "last_verified": _verified_summary(receipt) if receipt is not None else None,
    }
    if age_seconds is not None:
        result["attempt_age_seconds"] = age_seconds
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--attempt", type=Path, default=DEFAULT_STATE_DIR / "latest-attempt.json")
    parser.add_argument("--receipt", type=Path, default=DEFAULT_STATE_DIR / "latest.json")
    parser.add_argument("--now", help="RFC 3339 UTC timestamp used for deterministic checks")
    parser.add_argument(
        "--stale-after-seconds", type=int, default=DEFAULT_STALE_AFTER_SECONDS,
    )
    parser.add_argument(
        "--stalled-after-seconds", type=int, default=DEFAULT_STALLED_AFTER_SECONDS,
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    now = _timestamp(args.now) if args.now else datetime.now(timezone.utc)
    if now is None or args.stale_after_seconds < 1 or args.stalled_after_seconds < 1:
        raise SystemExit("invalid status time or threshold")
    try:
        attempt = _read_object(args.attempt)
    except StatusInputError as error:
        result = {
            "schema_version": 1,
            "scheduler": "launchd",
            "label": LABEL,
            "checked_at": now.isoformat().replace("+00:00", "Z"),
            "state": "unknown",
            "reason": str(error),
            "latest_attempt": None,
            "last_verified": None,
        }
    else:
        try:
            receipt = _read_object(args.receipt)
        except StatusInputError:
            receipt = None
        result = build_status(
            attempt,
            receipt,
            now=now,
            stale_after_seconds=args.stale_after_seconds,
            stalled_after_seconds=args.stalled_after_seconds,
            launchd_state=probe_launchd(),
        )
    print(json.dumps(result, ensure_ascii=True, separators=(",", ":"), sort_keys=True))
    return 0 if result["state"] in {"healthy", "running"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
