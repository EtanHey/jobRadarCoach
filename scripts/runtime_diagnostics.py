"""Private, durable crash diagnostics, separate from ephemeral supervisor state."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
from typing import TYPE_CHECKING
from uuid import uuid4

if TYPE_CHECKING:
    from scripts.runtime_process import RuntimeContext


def create_run_logs(context: RuntimeContext, service: str) -> Path:
    root = context.state_dir.parent / ".run-logs"
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    root.chmod(0o700)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    directory = root / f"{stamp}-{service}-{uuid4().hex}"
    directory.mkdir(mode=0o700)
    return directory


def private_append(path: Path):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    os.fchmod(descriptor, 0o600)
    return os.fdopen(descriptor, "a", encoding="utf-8")


def record_event(directory: Path | None, service: str, event: str, **values) -> None:
    if directory is None:
        return
    try:
        with private_append(directory / "events.jsonl") as output:
            output.write(json.dumps({
                "at": datetime.now(timezone.utc).isoformat(), "service": service,
                "event": event, **values,
            }) + "\n")
    except OSError:
        # A full disk must not prevent terminating an owned process.
        print(f"Warning: cannot append runtime diagnostics in {directory}", file=sys.stderr)


def validate_run_logs(context: RuntimeContext, directory: Path) -> Path:
    root = (context.state_dir.parent / ".run-logs").resolve()
    if directory.resolve().parent != root:
        raise RuntimeError("diagnostic path is outside this runtime's log directory")
    return directory


def retain_receipt(context: RuntimeContext, directory: Path, receipt: Path) -> None:
    validate_run_logs(context, directory)
    if receipt.is_file():
        # Snapshot only; this file must never be treated as a current readiness receipt.
        with private_append(directory / "receipt-snapshot.json") as output:
            output.seek(0)
            output.truncate()
            output.write(receipt.read_text())
