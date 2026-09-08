"""Exact-target Tailscale Serve lifecycle for ``./run``."""

import json
import subprocess
from typing import Any, Sequence

from scripts.runtime_control import PartialStartError
from scripts.runtime_process import Probe, RuntimeContext


def _result(context: RuntimeContext, command: Sequence[str]):
    try:
        return context.run(command, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return None


def _json(context: RuntimeContext, command: Sequence[str]) -> dict[str, Any] | None:
    result = _result(context, command)
    if result is None or result.returncode:
        return None
    try:
        value = json.loads(result.stdout)
    except (json.JSONDecodeError, UnicodeError):
        return None
    return value if isinstance(value, dict) else None


def _http(context: RuntimeContext, url: str) -> bool:
    result = _result(context, ("curl", "-fsS", "-o", "/dev/null", "--max-time", "2", url))
    return result is not None and result.returncode == 0


class TailscaleServeService:
    name = "tailscale-serve"
    desired = {
        "https:8445": "http://127.0.0.1:3410",
        "https:8446": "http://127.0.0.1:17880",
        "tcp:7881": "127.0.0.1:17881",
    }

    def _targets(self, context: RuntimeContext) -> dict[str, str | None] | None:
        serve = _json(context, ("tailscale", "serve", "status", "--json"))
        status = _json(context, ("tailscale", "status", "--json"))
        try:
            dns = status["Self"]["DNSName"].rstrip(".")
            tcp, web = serve.get("TCP", {}), serve.get("Web", {})
            entry = tcp.get("7881")
            targets: dict[str, str | None] = {
                "tcp:7881": None if entry is None else entry.get("TCPForward", "<occupied>"),
            }
            for port in (8445, 8446):
                entry = tcp.get(str(port))
                handlers = web.get(f"{dns}:{port}", {}).get("Handlers", {})
                valid = entry == {"HTTPS": True} and set(handlers) == {"/"}
                targets[f"https:{port}"] = (
                    None if entry is None and not handlers
                    else handlers.get("/", {}).get("Proxy", "<occupied>") if valid
                    else "<occupied>"
                )
            return targets
        except (AttributeError, KeyError, TypeError):
            return None

    def probe(self, context: RuntimeContext) -> Probe:
        targets = self._targets(context)
        if targets is None:
            return Probe(False, "Tailscale status unavailable")
        wrong = [key for key, target in targets.items() if target not in (None, self.desired[key])]
        missing = [key for key, target in targets.items() if target is None]
        if wrong:
            return Probe(False, f"conflicting mappings: {','.join(wrong)}")
        status = _json(context, ("tailscale", "status", "--json")) or {}
        dns = status.get("Self", {}).get("DNSName", "").rstrip(".")
        reachable = bool(dns) and all(_http(context, f"https://{dns}:{port}/") for port in (8445, 8446))
        healthy = not missing and reachable
        detail = "exact mappings reachable" if healthy else (
            f"missing: {','.join(missing)}" if missing else "tailnet HTTPS probes failed"
        )
        return Probe(healthy, detail)

    def start(self, context: RuntimeContext) -> dict[str, Any]:
        targets = self._targets(context)
        if targets is None:
            raise RuntimeError("Tailscale status unavailable")
        conflicts = [key for key, target in targets.items() if target not in (None, self.desired[key])]
        if conflicts:
            raise RuntimeError(f"refusing to replace mappings: {','.join(conflicts)}")
        created: list[str] = []
        try:
            for key, target in self.desired.items():
                if targets[key] is not None:
                    continue
                if context.stop_requested():
                    raise InterruptedError("stop requested while adding Tailscale mappings")
                kind, port = key.split(":")
                destination = f"tcp://{target}" if kind == "tcp" else target
                result = _result(context, ("tailscale", "serve", "--bg", f"--{kind}={port}", destination))
                current = self._targets(context)
                if current is not None and current.get(key) == target:
                    created.append(key)
                if result is None or result.returncode:
                    raise RuntimeError(f"failed to create {key}")
                if key not in created:
                    created.append(key)
        except BaseException as error:
            self._rollback(context, created, error)
        if not created or not self.probe(context).healthy:
            self._rollback(context, created, RuntimeError("Tailscale mappings did not become healthy"))
        return {"created": created, "targets": {key: self.desired[key] for key in created}}

    def owns(self, context: RuntimeContext, identity: dict[str, Any]) -> bool:
        created, recorded = identity.get("created"), identity.get("targets")
        if not isinstance(created, list) or not created or not isinstance(recorded, dict):
            return False
        targets = self._targets(context)
        return targets is not None and all(
            key in self.desired and recorded.get(key) == self.desired[key] == targets.get(key)
            for key in created
        )

    def stop(self, context: RuntimeContext, identity: dict[str, Any]) -> None:
        if not self.owns(context, identity):
            raise RuntimeError("Tailscale mapping identity changed; refusing cleanup")
        self._remove(context, identity["created"])

    def _remove(self, context: RuntimeContext, keys: Sequence[str]) -> None:
        targets = self._targets(context) or {}
        for key in reversed(keys):
            if targets.get(key) != self.desired.get(key):
                raise RuntimeError(f"mapping {key} changed; refusing cleanup")
            kind, port = key.split(":")
            result = _result(context, ("tailscale", "serve", f"--{kind}={port}", "off"))
            if result is None or result.returncode:
                raise RuntimeError(f"failed to remove {key}")
            current = self._targets(context)
            if current is None or current.get(key) is not None:
                raise RuntimeError(f"mapping {key} still present after cleanup")

    def _rollback(self, context: RuntimeContext, created: list[str], error: BaseException) -> None:
        try:
            self._remove(context, created)
        except Exception as cleanup_error:
            identity = {"created": created, "targets": {key: self.desired[key] for key in created}}
            raise PartialStartError(f"{error}; rollback unconfirmed: {cleanup_error}", identity) from error
        raise error
