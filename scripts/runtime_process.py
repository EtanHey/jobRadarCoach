"""Process identity and foreground-command adapter for the run supervisor."""

from __future__ import annotations

import os
from pathlib import Path
import signal
import subprocess
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Sequence


Identity = dict[str, Any]


@dataclass(frozen=True)
class Probe:
    healthy: bool
    detail: str = ""


@dataclass
class RuntimeContext:
    repo_root: Path
    state_dir: Path
    qa_mode: bool = False
    stop_requested: Callable[[], bool] = field(default=lambda: False, repr=False)

    def run(
        self,
        command: Sequence[str],
        *,
        cwd: Path | None = None,
        env: Mapping[str, str] | None = None,
        timeout: float = 10,
    ) -> subprocess.CompletedProcess[str]:
        merged_env = os.environ.copy()
        if env:
            merged_env.update(env)
        if self.qa_mode:
            merged_env["VOICE_QA_MODE"] = "1"
        else:
            merged_env.pop("VOICE_QA_MODE", None)
        return subprocess.run(
            list(command), cwd=cwd or self.repo_root, env=merged_env,
            text=True, capture_output=True, timeout=timeout, check=False,
        )


def process_snapshot(pid: int) -> Identity | None:
    try:
        pgid = os.getpgid(pid)
        start = subprocess.run(
            ["ps", "-o", "lstart=", "-p", str(pid)], text=True,
            capture_output=True, timeout=2, check=False,
        ).stdout.strip()
        argv = subprocess.run(
            ["ps", "-ww", "-o", "command=", "-p", str(pid)], text=True,
            capture_output=True, timeout=2, check=False,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    return {
        "pid": pid, "pgid": pgid, "start": start, "argv": argv, "argv_verified": True,
    } if start and argv else None


def _group_snapshots(pgid: int) -> list[Identity]:
    try:
        output = subprocess.run(
            ["ps", "-axo", "pid=,pgid=,lstart=,command="], text=True,
            capture_output=True, timeout=2, check=False,
        ).stdout
    except subprocess.SubprocessError:
        return []
    members = []
    for line in output.splitlines():
        fields = line.split(None, 7)
        if len(fields) != 8:
            continue
        try:
            pid, candidate_pgid = int(fields[0]), int(fields[1])
        except ValueError:
            continue
        if candidate_pgid == pgid:
            members.append({
                "pid": pid, "pgid": candidate_pgid,
                "start": " ".join(fields[2:7]), "argv": fields[7], "argv_verified": True,
            })
    return members


def same_process(identity: Identity) -> bool:
    try:
        current = process_snapshot(int(identity["pid"]))
    except (KeyError, TypeError, ValueError):
        return False
    keys = ["pid", "pgid", "start"]
    if identity.get("argv_verified"):
        keys.append("argv")
    return current is not None and all(current.get(key) == identity.get(key) for key in keys)


def _group_exists(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
        return True
    except ProcessLookupError:
        return False


def _identity_state(identity: Identity) -> str:
    try:
        pid, pgid = int(identity["pid"]), int(identity["pgid"])
    except (KeyError, TypeError, ValueError):
        return "mismatch"
    current = process_snapshot(pid)
    if current is not None:
        return "same" if same_process(identity) else "mismatch"
    if pgid != pid:
        return "mismatch"
    if not _group_exists(pgid):
        return "stopped"
    recorded = {
        (item.get("pid"), item.get("start"))
        for item in identity.get("members", []) if isinstance(item, dict)
    }
    current = {(item["pid"], item["start"]) for item in _group_snapshots(pgid)}
    return "group" if recorded & current else "mismatch"


class ProcessService:
    """Adapter for a foreground command whose readiness has an explicit probe."""

    def __init__(
        self,
        name: str,
        command: Sequence[str],
        probe: Callable[[RuntimeContext], Probe],
        *,
        cwd: Path | None = None,
        env: Mapping[str, str] | None = None,
        startup_timeout: float = 20,
        shutdown_timeout: float = 10,
        readiness_interval: float = 0.5,
    ) -> None:
        self.name, self.command, self._probe = name, tuple(command), probe
        self.cwd, self.env = cwd, dict(env or {})
        self.startup_timeout, self.shutdown_timeout = startup_timeout, shutdown_timeout
        self.readiness_interval = readiness_interval
        self._children: dict[int, subprocess.Popen[str]] = {}

    def probe(self, context: RuntimeContext) -> Probe:
        return self._probe(context)

    def start(self, context: RuntimeContext) -> Identity:
        merged_env = os.environ.copy()
        merged_env.update(self.env)
        if context.qa_mode:
            merged_env["VOICE_QA_MODE"] = "1"
        else:
            merged_env.pop("VOICE_QA_MODE", None)
        child = subprocess.Popen(
            self.command, cwd=self.cwd or context.repo_root, env=merged_env,
            text=True, start_new_session=True,
        )
        self._children[child.pid] = child
        identity = process_snapshot(child.pid)
        if identity is None:
            self._terminate(child.pid, None)
            raise RuntimeError("could not capture process identity")
        identity["argv_verified"] = False
        try:
            deadline = time.monotonic() + self.startup_timeout
            while time.monotonic() < deadline:
                if context.stop_requested():
                    raise InterruptedError("startup interrupted")
                if child.poll() is not None:
                    raise RuntimeError(f"exited during startup ({child.returncode})")
                if self.probe(context).healthy:
                    if same_process(identity):
                        verified = process_snapshot(child.pid)
                        if verified is None:
                            raise RuntimeError("could not verify process identity")
                        verified["members"] = [
                            item for item in _group_snapshots(int(verified["pgid"]))
                            if item["pid"] != verified["pid"]
                        ]
                        return verified
                    raise RuntimeError("process identity changed during startup")
                time.sleep(self.readiness_interval)
            raise RuntimeError("startup health check timed out")
        except BaseException:
            self._terminate(child.pid, identity)
            raise

    def owns(self, context: RuntimeContext, identity: Identity) -> bool:
        del context
        return _identity_state(identity) != "mismatch"

    def stop(self, context: RuntimeContext, identity: Identity) -> None:
        del context
        if _identity_state(identity) == "mismatch":
            raise RuntimeError("process identity changed; refusing to signal")
        self._terminate(int(identity["pid"]), identity)

    def _terminate(self, pid: int, identity: Identity | None) -> None:
        state = _identity_state(identity) if identity is not None else "same"
        if state == "mismatch":
            raise RuntimeError("process identity changed; refusing to signal")
        child = self._children.get(pid)
        if state == "stopped":
            if child is not None:
                child.poll()
            return
        pgid = int(identity["pgid"]) if identity is not None else os.getpgid(pid)
        try:
            os.killpg(pgid, signal.SIGTERM)
        except ProcessLookupError:
            if child is not None:
                child.poll()
            return
        deadline = time.monotonic() + self.shutdown_timeout
        while time.monotonic() < deadline:
            if child is not None:
                child.poll()
            if not _group_exists(pgid):
                if child is not None:
                    child.wait(timeout=2)
                return
            time.sleep(0.05)
        if identity is None or _identity_state(identity) in {"same", "group"}:
            try:
                os.killpg(pgid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        if child is not None:
            try:
                child.wait(timeout=2)
            except subprocess.TimeoutExpired:
                pass
        deadline = time.monotonic() + 2
        while _group_exists(pgid) and time.monotonic() < deadline:
            time.sleep(0.05)
        if _group_exists(pgid):
            raise RuntimeError("process group did not exit")
