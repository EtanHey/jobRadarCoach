"""Small, adapter-driven foreground supervisor for ``./run``."""

from __future__ import annotations

import argparse
import fcntl
import importlib
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any, Protocol, Sequence

from scripts.runtime_diagnostics import create_run_logs, record_event
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


def _identity_alive(context: RuntimeContext, service: Service, identity: Identity) -> bool:
    try:
        pid = int(identity["pid"])
    except (KeyError, TypeError, ValueError):
        return False
    if isinstance(service, ProcessService):
        child = service._children.get(pid)
        if child is not None and child.poll() is not None:
            return False
    if not _same_process(identity):
        return False
    try:
        result = context.run(("ps", "-o", "state=", "-p", str(pid)), timeout=2)
    except (OSError, subprocess.SubprocessError):
        return False
    state = result.stdout.strip()
    return result.returncode == 0 and bool(state) and not state.startswith("Z")


class Supervisor:
    def __init__(self, context: RuntimeContext, services: Sequence[Service], *,
                 services_module: str | None = None) -> None:
        self.context, self.services = context, list(services)
        self.services_module = services_module
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

    def _write_state(self, entries: list[dict[str, Any]], degraded: dict[str, dict[str, str]] | None = None) -> None:
        supervisor = _process_snapshot(os.getpid())
        if supervisor is None:
            raise RuntimeError("could not capture supervisor identity")
        _atomic_json(self.state_path, {
            "supervisor": supervisor, "qa_mode": self.context.qa_mode,
            "services": entries, "degraded": degraded or {},
        })

    def _wait_for_locked_mode(self, timeout: float = 0.75) -> bool | None:
        deadline = time.monotonic() + timeout
        while True:
            state = self._read_state() or {}
            owner, mode = state.get("supervisor"), state.get("qa_mode")
            if isinstance(owner, dict) and isinstance(mode, bool) and _same_process(owner):
                return mode
            if time.monotonic() >= deadline:
                return None
            time.sleep(0.02)

    def up(self) -> int:
        try:
            health_failure_threshold = int(os.environ.get("RUN_HEALTH_FAILURE_THRESHOLD", "3"))
        except ValueError as error:
            raise ValueError("RUN_HEALTH_FAILURE_THRESHOLD must be an integer") from error
        if health_failure_threshold < 2:
            raise ValueError("RUN_HEALTH_FAILURE_THRESHOLD must be at least 2")
        try:
            health_interval = float(os.environ.get("RUN_HEALTH_INTERVAL", "5"))
        except ValueError as error:
            raise ValueError("RUN_HEALTH_INTERVAL must be a number") from error
        if not math.isfinite(health_interval) or health_interval <= 0:
            raise ValueError("RUN_HEALTH_INTERVAL must be greater than zero")
        self.context.state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        lock = self.lock_path.open("a+")
        os.chmod(self.lock_path, 0o600)
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            mode = self._wait_for_locked_mode()
            if mode is None:
                print("supervisor initialization state unknown; retry shortly", file=sys.stderr)
                return 1
            if mode is self.context.qa_mode:
                print("supervisor already running in requested mode")
                return 0
            print("supervisor mode differs; run './run down' before changing mode", file=sys.stderr)
            return 1
        previous = self._read_state() or {}
        retained = previous.get("cleanup_failures", [])
        owned = [item for item in previous.get("services", []) if item.get("mode") == "owned"]
        if retained or owned:
            print("supervisor: recovering previous owned resources before starting", flush=True)
            if self._cleanup_recorded_state(previous) != 0:
                print("supervisor: recovery incomplete; refusing up", file=sys.stderr)
                return 1
        entries: list[dict[str, Any]] = []
        stop_event = threading.Event()
        shutdown_reason: str | None = None
        try:
            diagnostic_dir = create_run_logs(self.context, "supervisor")
        except OSError:
            diagnostic_dir = None
            print("Warning: cannot create runtime diagnostics", file=sys.stderr, flush=True)
        record_event(diagnostic_dir, "supervisor", "started", qa_mode=self.context.qa_mode)

        def request_stop(signum: int, _frame: Any) -> None:
            nonlocal shutdown_reason
            try:
                signal_name = signal.Signals(signum).name
            except ValueError:
                signal_name = str(signum)
            shutdown_reason = f"signal:{signal_name}"
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
                if probe.healthy and getattr(service, "lifecycle_owned", False) is not True:
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
            failure_counts: dict[str, int] = {}
            degraded: dict[str, dict[str, str]] = {}

            def persist_health_state(next_degraded: dict[str, dict[str, str]]) -> bool:
                try:
                    self._write_state(entries, next_degraded)
                    return True
                except Exception as error:
                    print(
                        f"supervisor: cannot persist health state ({type(error).__name__}); "
                        "stack remains running",
                        file=sys.stderr,
                        flush=True,
                    )
                    record_event(
                        diagnostic_dir, "supervisor", "health_state_write_failed",
                        error_type=type(error).__name__,
                    )
                    return False

            while not stop_event.is_set():
                for service, entry in zip(self.services, entries):
                    if stop_event.is_set():
                        break
                    try:
                        probe = service.probe(self.context)
                    except Exception as error:
                        probe = Probe(False, f"health probe raised {type(error).__name__}")
                    if probe.healthy:
                        failure_counts.pop(service.name, None)
                        previous = degraded.get(service.name)
                        if previous is not None:
                            next_degraded = dict(degraded)
                            next_degraded.pop(service.name)
                            if not persist_health_state(next_degraded):
                                continue
                            degraded = next_degraded
                            print(f"{service.name}: recovered ({probe.detail or 'healthy'})", flush=True)
                            record_event(
                                diagnostic_dir,
                                "supervisor",
                                "recovered",
                                affected_service=service.name,
                                mode=entry.get("mode"),
                                previous_reason=previous["reason"],
                                previous_condition=previous["condition"],
                            )
                        continue
                    failures = failure_counts.get(service.name, 0) + 1
                    failure_counts[service.name] = failures
                    if failures < health_failure_threshold:
                        print(
                            f"{service.name}: health check failed "
                            f"({failures}/{health_failure_threshold}); retrying",
                            file=sys.stderr,
                            flush=True,
                        )
                        continue
                    reason = probe.detail or "health check failed"
                    identity = entry.get("identity")
                    stopped = (
                        entry.get("mode") == "owned"
                        and isinstance(identity, dict)
                        and not _identity_alive(self.context, service, identity)
                    )
                    condition = "stopped" if stopped else "readiness_failed"
                    current = {"condition": condition, "reason": reason}
                    if degraded.get(service.name) != current:
                        next_degraded = {**degraded, service.name: current}
                        if not persist_health_state(next_degraded):
                            continue
                        degraded = next_degraded
                        state_label = "stopped/degraded" if stopped else "degraded"
                        print(
                            f"{service.name}: {state_label} after {failures} consecutive failures "
                            f"({reason}); stack remains running",
                            file=sys.stderr,
                            flush=True,
                        )
                        record_event(
                            diagnostic_dir,
                            "supervisor",
                            "degraded",
                            affected_service=service.name,
                            mode=entry.get("mode"),
                            condition=condition,
                            reason=reason,
                            consecutive_failures=failures,
                        )
                stop_event.wait(health_interval)
        except InterruptedError:
            shutdown_reason = shutdown_reason or "startup_interrupted"
            print("supervisor: startup interrupted", flush=True)
        except Exception as error:
            shutdown_reason = shutdown_reason or f"supervisor_error:{type(error).__name__}"
            print(f"startup failed: {error}", file=sys.stderr, flush=True)
            exit_code = 1
        finally:
            retained, failures = self._cleanup(entries)
            if failures:
                state = self._read_state() or {}
                state["services"] = retained
                state["cleanup_failures"] = failures
                _atomic_json(self.state_path, state)
            else:
                self.state_path.unlink(missing_ok=True)
            signal.signal(signal.SIGINT, old_int)
            signal.signal(signal.SIGTERM, old_term)
            if failures:
                exit_code = 1
            record_event(
                diagnostic_dir, "supervisor", "shutdown",
                reason=shutdown_reason or "requested", exit_code=exit_code,
                cleanup_failure_count=len(failures),
            )
        return exit_code

    def _cleanup(
        self, entries: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], list[str]]:
        by_name = {service.name: service for service in self.services}
        retained: list[dict[str, Any]] = []
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
                retained.insert(0, entry)
                message = f"{entry.get('name', '?')}: cleanup failed: {error}"
                failures.append(message)
                print(message, file=sys.stderr, flush=True)
        return retained, failures

    def status(self) -> int:
        state = self._read_state() or {}
        owner = state.get("supervisor")
        active = isinstance(owner, dict) and _same_process(owner)
        modes = {item.get("name"): item.get("mode") for item in state.get("services", [])}
        raw_degraded = state.get("degraded", {})
        degraded = {
            name: item
            for name, item in raw_degraded.items()
            if (
                isinstance(name, str)
                and isinstance(item, dict)
                and item.get("condition") in {"readiness_failed", "stopped"}
                and isinstance(item.get("reason"), str)
            )
        } if active and isinstance(raw_degraded, dict) else {}
        if active and not isinstance(raw_degraded, dict):
            degraded = {
                "supervisor": {"condition": "readiness_failed", "reason": "invalid degraded state"},
            }
        probes: dict[str, Probe] = {}
        current_failures: dict[str, str] = {}
        for service in self.services:
            try:
                probe = service.probe(self.context)
            except Exception as error:
                probe = Probe(False, f"health probe raised {type(error).__name__}")
            probes[service.name] = probe
            if active and not probe.healthy:
                current_failures[service.name] = probe.detail or "health check failed"
        failures = state.get("cleanup_failures", []) if not active else []
        suffix = f" (cleanup failed: {'; '.join(failures)})" if failures else ""
        mode = "unknown" if "qa_mode" not in state else ("QA" if state["qa_mode"] else "normal")
        if degraded:
            reasons = "; ".join(
                f"{name}: {item['condition'].replace('_', ' ')}: {item['reason']}"
                for name, item in sorted(degraded.items())
            )
            suffix = f" (degraded: {reasons})"
        elif active and current_failures:
            reasons = "; ".join(
                f"{name}: {reason}" for name, reason in sorted(current_failures.items())
            )
            suffix = f" (health check failed; waiting for threshold: {reasons})"
        label = (
            "degraded" if active and degraded
            else "checking" if active and current_failures
            else "running" if active
            else "stopped"
        )
        print(f"supervisor: {label} mode={mode}{suffix}")
        for service in self.services:
            probe = probes[service.name]
            mode = modes.get(service.name) if active else None
            label = mode or ("external" if probe.healthy else "stopped")
            if service.name in degraded:
                condition = degraded[service.name]["condition"]
                label = f"{label} stopped/degraded" if condition == "stopped" else f"{label} degraded"
                detail = degraded[service.name]["reason"]
            elif active and not probe.healthy:
                label = f"{label} checking"
                detail = current_failures[service.name]
            else:
                detail = probe.detail or ("healthy" if probe.healthy else "not healthy")
            print(f"{service.name}: {label} ({detail})")
        return 0 if active and not degraded and not current_failures else 1

    def down(self, timeout: float = 20) -> int:
        state = self._read_state()
        identity = state.get("supervisor") if state else None
        if not isinstance(identity, dict):
            print("supervisor: stopped")
            return 0
        failures = state.get("cleanup_failures", []) if state else []
        if failures:
            return self._retry_cleanup()
        if not _same_process(identity):
            return self._retry_cleanup()
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

    def _retry_cleanup(self) -> int:
        self.context.state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        with self.lock_path.open("a+") as lock:
            os.chmod(self.lock_path, 0o600)
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                print("supervisor: cleanup retry locked by running supervisor", file=sys.stderr)
                return 1
            state = self._read_state()
            if not state:
                print("supervisor: stopped")
                return 0
            return self._cleanup_recorded_state(state)

    def _cleanup_recorded_state(self, state: dict[str, Any]) -> int:
        """Recover exact recorded resources while caller retains the exclusive lock."""
        owner = state.get("supervisor")
        if isinstance(owner, dict) and _same_process(owner):
            print("supervisor: cleanup still owned by running supervisor", file=sys.stderr)
            return 1
        recorded_mode = state.get("qa_mode")
        if not isinstance(recorded_mode, bool):
            print("supervisor: previous mode unknown; refusing recovery", file=sys.stderr)
            return 1
        context = RuntimeContext(self.context.repo_root, self.context.state_dir, qa_mode=recorded_mode)
        if self.services_module is not None:
            services = _load_services(self.services_module, context)
        elif recorded_mode == self.context.qa_mode:
            services = self.services
        else:
            print("supervisor: previous mode adapters unavailable", file=sys.stderr)
            return 1
        cleanup = Supervisor(context, services)
        entries = state.get("services", [])
        if not isinstance(entries, list) or any(not isinstance(row, dict) for row in entries):
            print("supervisor: invalid retained cleanup state", file=sys.stderr)
            return 1
        interrupted_signal: int | None = None

        def defer_interrupt(signum: int, _frame: Any) -> None:
            nonlocal interrupted_signal
            interrupted_signal = interrupted_signal or signum

        old_int = signal.signal(signal.SIGINT, defer_interrupt)
        old_term = signal.signal(signal.SIGTERM, defer_interrupt)
        try:
            retained, retry_failures = cleanup._cleanup(entries)
            if retry_failures:
                state["services"] = retained
                state["cleanup_failures"] = retry_failures
                _atomic_json(self.state_path, state)
                print(
                    "supervisor: cleanup failed: " + "; ".join(retry_failures),
                    file=sys.stderr,
                )
                if interrupted_signal is not None:
                    print("supervisor: interrupted; cleanup state retained", file=sys.stderr)
                return 1
            self.state_path.unlink(missing_ok=True)
            if interrupted_signal is not None:
                print("supervisor: cleanup completed after interrupt", file=sys.stderr)
                return 1
            print("supervisor: stopped")
            return 0
        finally:
            signal.signal(signal.SIGINT, old_int)
            signal.signal(signal.SIGTERM, old_term)

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
    recorded_state: dict[str, Any] | None = None
    if args.command != "up":
        try:
            value = json.loads((state_dir / "state.json").read_text())
            recorded_state = value if isinstance(value, dict) else None
            recorded = recorded_state.get("qa_mode") if recorded_state else None
            if isinstance(recorded, bool):
                qa_mode = recorded
        except (OSError, json.JSONDecodeError, AttributeError):
            pass
    context = RuntimeContext(repo_root=repo_root, state_dir=state_dir, qa_mode=qa_mode)
    if args.command == "up" and qa_mode:
        print("*** READ-ONLY QA MODE REQUESTED: adapters must enforce read-only behavior ***", flush=True)
    try:
        services = _load_services(args.services_module, context) if args.command != "down" else []
        supervisor = Supervisor(context, services, services_module=args.services_module)
        return getattr(supervisor, args.command)()
    except Exception as error:
        if args.command == "status":
            Supervisor(context, []).status()
        print(f"configuration error: {error}", file=sys.stderr)
        return 2
