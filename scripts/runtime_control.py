"""Small, adapter-driven foreground supervisor for ``./run``."""

from __future__ import annotations

import argparse
import fcntl
import importlib
import json
import os
from pathlib import Path
import signal
import sys
import tempfile
import threading
import time
from typing import Any, Protocol, Sequence

from scripts.runtime_process import (
    Identity,
    Probe,
    ProcessService as ProcessService,
    RuntimeContext,
    process_snapshot as _process_snapshot,
    same_process as _same_process,
)


class Service(Protocol):
    name: str

    def probe(self, context: RuntimeContext) -> Probe: ...
    def start(self, context: RuntimeContext) -> Identity: ...
    def owns(self, context: RuntimeContext, identity: Identity) -> bool: ...
    def stop(self, context: RuntimeContext, identity: Identity) -> None: ...


class PartialStartError(RuntimeError):
    """A start failed after creating a resource that still needs cleanup."""

    def __init__(self, message: str, owned_identity: Identity) -> None:
        super().__init__(message)
        self.owned_identity = owned_identity


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    fd, temporary = tempfile.mkstemp(prefix="state-", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w") as handle:
            json.dump(value, handle, sort_keys=True)
            handle.write("\n")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class Supervisor:
    def __init__(self, context: RuntimeContext, services: Sequence[Service]) -> None:
        self.context, self.services = context, list(services)
        self.state_path = context.state_dir / "state.json"
        self.lock_path = context.state_dir / "up.lock"
        if len({service.name for service in services}) != len(services):
            raise ValueError("service names must be unique")

    def _read_state(self) -> dict[str, Any] | None:
        try:
            value = json.loads(self.state_path.read_text())
            return value if isinstance(value, dict) else None
        except (OSError, json.JSONDecodeError):
            return None

    def _write_state(self, entries: list[dict[str, Any]]) -> None:
        supervisor = _process_snapshot(os.getpid())
        if supervisor is None:
            raise RuntimeError("could not capture supervisor identity")
        _atomic_json(self.state_path, {
            "supervisor": supervisor, "qa_mode": self.context.qa_mode, "services": entries,
        })

    def up(self) -> int:
        self.context.state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        lock = self.lock_path.open("a+")
        os.chmod(self.lock_path, 0o600)
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            state = self._read_state() or {}
            if state.get("qa_mode") is self.context.qa_mode:
                print("supervisor already running in requested mode")
                return 0
            print("supervisor mode differs; run './run down' before changing mode", file=sys.stderr)
            return 1
        previous = self._read_state() or {}
        retained = previous.get("cleanup_failures", [])
        owned = [item for item in previous.get("services", []) if item.get("mode") == "owned"]
        if retained or owned:
            reason = "cleanup failure" if retained else "stale owned resources"
            print(f"supervisor: retained state has {reason}; refusing up", file=sys.stderr)
            return 1
        entries: list[dict[str, Any]] = []
        stop_event = threading.Event()

        def request_stop(_signum: int, _frame: Any) -> None:
            stop_event.set()

        old_int = signal.signal(signal.SIGINT, request_stop)
        old_term = signal.signal(signal.SIGTERM, request_stop)
        self.context.stop_requested = stop_event.is_set
        exit_code = 0
        try:
            self.state_path.unlink(missing_ok=True)
            self._write_state(entries)
            for service in self.services:
                if stop_event.is_set():
                    raise InterruptedError("startup interrupted")
                probe = service.probe(self.context)
                if probe.healthy:
                    entries.append({"name": service.name, "mode": "borrowed", "detail": probe.detail})
                    print(f"{service.name}: borrowed ({probe.detail or 'healthy'})", flush=True)
                    if stop_event.is_set():
                        raise InterruptedError("startup interrupted")
                    continue
                try:
                    identity = service.start(self.context)
                except PartialStartError as error:
                    entries.append({
                        "name": service.name, "mode": "owned", "identity": error.owned_identity,
                    })
                    self._write_state(entries)
                    raise
                entries.append({"name": service.name, "mode": "owned", "identity": identity})
                self._write_state(entries)
                print(f"{service.name}: owned (healthy)", flush=True)
                if stop_event.is_set():
                    raise InterruptedError("startup interrupted")
            self._write_state(entries)
            print("supervisor: running; Ctrl-C stops owned resources", flush=True)
            while not stop_event.is_set():
                for service, entry in zip(self.services, entries):
                    if not service.probe(self.context).healthy:
                        print(f"{service.name}: unhealthy; shutting down", file=sys.stderr, flush=True)
                        exit_code = 1
                        stop_event.set()
                        break
                stop_event.wait(float(os.environ.get("RUN_HEALTH_INTERVAL", "5")))
        except InterruptedError:
            print("supervisor: startup interrupted", flush=True)
        except Exception as error:
            print(f"startup failed: {error}", file=sys.stderr, flush=True)
            exit_code = 1
        finally:
            failures = self._cleanup(entries)
            if failures:
                state = self._read_state() or {}
                state["cleanup_failures"] = failures
                _atomic_json(self.state_path, state)
            else:
                self.state_path.unlink(missing_ok=True)
            signal.signal(signal.SIGINT, old_int)
            signal.signal(signal.SIGTERM, old_term)
            if failures:
                exit_code = 1
        return exit_code

    def _cleanup(self, entries: list[dict[str, Any]]) -> list[str]:
        by_name = {service.name: service for service in self.services}
        failures: list[str] = []
        for entry in reversed(entries):
            if entry.get("mode") != "owned":
                continue
            service = by_name.get(entry.get("name"))
            identity = entry.get("identity")
            try:
                if service is None or not isinstance(identity, dict) or not service.owns(self.context, identity):
                    raise RuntimeError("ownership identity changed; refusing cleanup")
                service.stop(self.context, identity)
                print(f"{entry['name']}: stopped", flush=True)
            except Exception as error:
                message = f"{entry.get('name', '?')}: cleanup failed: {error}"
                failures.append(message)
                print(message, file=sys.stderr, flush=True)
        return failures

    def status(self) -> int:
        state = self._read_state() or {}
        owner = state.get("supervisor")
        active = isinstance(owner, dict) and _same_process(owner)
        modes = {item.get("name"): item.get("mode") for item in state.get("services", [])}
        failures = state.get("cleanup_failures", []) if not active else []
        suffix = f" (cleanup failed: {'; '.join(failures)})" if failures else ""
        mode = "unknown" if "qa_mode" not in state else ("QA" if state["qa_mode"] else "normal")
        print(f"supervisor: {'running' if active else 'stopped'} mode={mode}{suffix}")
        for service in self.services:
            probe = service.probe(self.context)
            mode = modes.get(service.name) if active else None
            label = mode or ("external" if probe.healthy else "stopped")
            print(f"{service.name}: {label} ({probe.detail or ('healthy' if probe.healthy else 'not healthy')})")
        return 0 if active else 1

    def down(self, timeout: float = 20) -> int:
        state = self._read_state()
        identity = state.get("supervisor") if state else None
        if not isinstance(identity, dict):
            print("supervisor: stopped")
            return 0
        failures = state.get("cleanup_failures", []) if state else []
        if failures:
            print("supervisor: cleanup failed: " + "; ".join(failures), file=sys.stderr)
            return 1
        if not _same_process(identity):
            print("supervisor: stale state; refusing to signal", file=sys.stderr)
            return 1
        os.kill(int(identity["pid"]), signal.SIGTERM)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not _same_process(identity):
                final_state = self._read_state() or {}
                failures = final_state.get("cleanup_failures", [])
                if failures:
                    print("supervisor: cleanup failed: " + "; ".join(failures), file=sys.stderr)
                    return 1
                print("supervisor: stopped")
                return 0
            time.sleep(0.05)
        print("supervisor: stop timed out", file=sys.stderr)
        return 1


def _load_services(module_name: str, context: RuntimeContext) -> Sequence[Service]:
    module = importlib.import_module(module_name)
    services = module.build_services(context)
    return list(services)


def main(*, repo_root: Path, argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(prog="./run")
    parser.add_argument("command", choices=("up", "down", "status"))
    parser.add_argument("--qa", action="store_true", help="request adapter-enforced read-only QA mode")
    parser.add_argument(
        "--services-module", default=os.environ.get("RUN_SERVICES_MODULE", "scripts.runtime_services")
    )
    args = parser.parse_args(argv)
    state_dir = Path(os.environ.get("RUN_SUPERVISOR_STATE_DIR", repo_root / ".run-state"))
    qa_mode = args.qa
    if args.command != "up":
        try:
            recorded = json.loads((state_dir / "state.json").read_text()).get("qa_mode")
            if isinstance(recorded, bool):
                qa_mode = recorded
        except (OSError, json.JSONDecodeError, AttributeError):
            pass
    context = RuntimeContext(repo_root=repo_root, state_dir=state_dir, qa_mode=qa_mode)
    if args.command == "up" and qa_mode:
        print("*** READ-ONLY QA MODE REQUESTED: adapters must enforce read-only behavior ***", flush=True)
    try:
        services = [] if args.command == "down" else _load_services(args.services_module, context)
        supervisor = Supervisor(context, services)
        return getattr(supervisor, args.command)()
    except Exception as error:
        if args.command == "status":
            Supervisor(context, []).status()
        print(f"configuration error: {error}", file=sys.stderr)
        return 2
