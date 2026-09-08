"""Disposable real-process adapters used only by supervisor tests."""

import os
from pathlib import Path
import sys

from scripts.runtime_process import Probe, ProcessService


WORKER = """
import os, pathlib, signal, sys, time
p = pathlib.Path(sys.argv[1]); p.write_text(str(os.getpid()))
def stop(*_):
    p.unlink(missing_ok=True); raise SystemExit(0)
signal.signal(signal.SIGINT, stop); signal.signal(signal.SIGTERM, stop)
while True: time.sleep(.05)
"""


def _alive(marker):
    try:
        os.kill(int(marker.read_text()), 0)
        return True
    except (OSError, ValueError):
        return False


def _service(name, marker, fail=False):
    command = [sys.executable, "-c", "import sys; sys.exit(7)"] if fail else [
        sys.executable, "-c", WORKER, str(marker)
    ]
    return ProcessService(
        name, command, lambda _context: Probe(_alive(marker), str(marker)),
        startup_timeout=.8, shutdown_timeout=.8, readiness_interval=.03,
    )


class _BadStop:
    name = "bad-stop"

    def __init__(self, marker):
        self.marker = marker

    def probe(self, _context):
        return Probe(self.marker.exists(), str(self.marker))

    def start(self, _context):
        self.marker.write_text("owned")
        return {"path": str(self.marker)}

    def owns(self, _context, identity):
        return identity == {"path": str(self.marker)}

    def stop(self, _context, _identity):
        raise RuntimeError("synthetic stop failure")


def build_services(_context):
    marker = Path(os.environ["TEST_MARKER"])
    mode = os.environ.get("TEST_MODE")
    if mode == "rollback":
        return [_service("first", marker), _service("broken", marker.with_name("broken"), True)]
    if mode == "interrupt":
        command = [sys.executable, "-c", WORKER, str(marker)]
        return [ProcessService(
            "slow", command, lambda _context: Probe(False),
            startup_timeout=30, readiness_interval=.03,
        )]
    if mode == "cleanup-fail":
        return [_BadStop(marker)]
    return [_service("tiny", marker)]
