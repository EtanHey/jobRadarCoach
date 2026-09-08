"""Read-only URL defaults for the guarded voice-QA runtime."""

from __future__ import annotations

from dataclasses import dataclass
import json
import ipaddress
import os
from pathlib import Path
import re
import shlex
import socket
import subprocess
from typing import Any, Mapping, Sequence
from urllib.parse import urlsplit

from scripts.runtime_process import RuntimeContext


@dataclass(frozen=True)
class QaRuntimeUrls:
    expected_livekit_url: str
    public_livekit_url: str


class QaConfigError(RuntimeError):
    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code


def _fail(code: str, detail: str) -> None:
    raise QaConfigError(code, detail)


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


def _valid_url(value: str, schemes: set[str]) -> bool:
    try:
        parsed = urlsplit(value)
        parsed.port
    except ValueError:
        return False
    return bool(
        parsed.scheme in schemes
        and parsed.hostname
        and parsed.username is None
        and parsed.password is None
        and parsed.path in {"", "/"}
        and not parsed.query
        and not parsed.fragment
    )


def _parse_options(arguments: Sequence[str], values: dict[str, str]) -> bool:
    aliases = {"--context": "context", "-n": "namespace", "--namespace": "namespace"}
    remaining = list(arguments)
    while remaining:
        key = aliases.get(remaining[0])
        if key is None or len(remaining) < 2 or key in values:
            return False
        values[key] = remaining[1]
        remaining = remaining[2:]
    return True


def _forward_shape(parts: Sequence[str]) -> tuple[bool, bool]:
    if not parts or Path(parts[0]).name != "kubectl" or parts.count("port-forward") != 1:
        return False, False
    command_at = parts.index("port-forward")
    values: dict[str, str] = {}
    if not _parse_options(parts[1:command_at], values):
        return False, False

    arguments = list(parts[command_at + 1:])
    while arguments and arguments[0].startswith("-"):
        flag = arguments[0]
        if flag == "--address":
            if len(arguments) < 2 or "address" in values:
                return False, False
            values["address"] = arguments[1]
        else:
            if not _parse_options(arguments[:2], values):
                return False, False
        arguments = arguments[2:]

    valid = (
        values.get("namespace") == "job-radar-coach"
        and values.get("context", "orbstack") == "orbstack"
        and values.get("address", "127.0.0.1") == "127.0.0.1"
        and arguments[0:1] in (["svc/livekit"], ["service/livekit"])
        and arguments[1:] == ["7880:7880"]
    )
    return valid, "context" in values


def _orbstack_peer(context: RuntimeContext, pid: str) -> bool:
    server = _result(context, (
        "kubectl", "--context", "orbstack", "config", "view", "--minify",
        "-o", "jsonpath={.clusters[0].cluster.server}",
    ))
    if server is None or server.returncode:
        _fail("orbstack_api_unavailable", "cannot resolve the named orbstack API endpoint")
    try:
        parsed = urlsplit(server.stdout.strip())
        port = parsed.port or 443
        if parsed.scheme != "https" or not parsed.hostname:
            raise ValueError
        addresses = {
            (ipaddress.ip_address(item[4][0].split("%", 1)[0]), port)
            for item in socket.getaddrinfo(parsed.hostname, port, type=socket.SOCK_STREAM)
        }
    except (OSError, TypeError, ValueError):
        _fail("orbstack_api_invalid", "named orbstack API endpoint is invalid")
    connections = _result(
        context, ("lsof", "-nP", "-a", "-p", pid, "-iTCP", "-sTCP:ESTABLISHED", "-Fn"),
    )
    if connections is None or connections.returncode:
        return False
    for line in connections.stdout.splitlines():
        peer = line[1:].partition("->")[2] if line.startswith("n") else ""
        host, separator, peer_port = peer.rpartition(":")
        try:
            candidate = (ipaddress.ip_address(host.strip("[]").split("%", 1)[0]), int(peer_port))
        except ValueError:
            continue
        if separator and candidate in addresses:
            return True
    return False


def _local_expected_url(context: RuntimeContext) -> str:
    listeners = _result(
        context, ("lsof", "-nP", "-iTCP:7880", "-sTCP:LISTEN", "-t"),
    )
    if listeners is None or listeners.returncode:
        _fail("livekit_forward_missing", "no listener exists on TCP 7880")
    pids = {line.strip() for line in listeners.stdout.splitlines() if line.strip().isdigit()}
    if len(pids) != 1:
        _fail("livekit_forward_ambiguous", "TCP 7880 does not have one identified listener")
    pid = pids.pop()
    process = _result(context, ("ps", "-ww", "-o", "command=", "-p", pid))
    try:
        parts = shlex.split(process.stdout.strip()) if process and not process.returncode else []
    except ValueError:
        parts = []
    valid, explicit_context = _forward_shape(parts)
    if not valid:
        _fail("livekit_forward_unfamiliar", "TCP 7880 is not the expected LiveKit port-forward")
    if not explicit_context and not _orbstack_peer(context, pid):
        _fail("livekit_forward_wrong_peer", "implicit port-forward is not connected to orbstack")

    sockets = _result(
        context,
        ("lsof", "-nP", "-a", "-p", pid, "-iTCP:7880", "-sTCP:LISTEN", "-Fn"),
    )
    names = set() if sockets is None or sockets.returncode else {
        line[1:] for line in sockets.stdout.splitlines() if line.startswith("n")
    }
    if not names or not names <= {"127.0.0.1:7880", "[::1]:7880"}:
        _fail("livekit_forward_not_loopback", "LiveKit port-forward is not loopback-only")
    return "ws://127.0.0.1:7880"


def _tailnet_public_url(context: RuntimeContext) -> str:
    serve = _json(context, ("tailscale", "serve", "status", "--json"))
    status = _json(context, ("tailscale", "status", "--json"))
    try:
        dns = status["Self"]["DNSName"].rstrip(".")
        tcp = serve["TCP"]["8446"]
        handlers = serve["Web"][f"{dns}:8446"]["Handlers"]
    except (AttributeError, KeyError, TypeError):
        _fail("public_livekit_mapping_missing", "Tailscale HTTPS 8446 status is incomplete")
    if not dns or re.fullmatch(r"[A-Za-z0-9.-]+", dns) is None:
        _fail("tailnet_dns_invalid", "Tailscale DNS name is unavailable or invalid")
    if tcp != {"HTTPS": True} or handlers != {"/": {"Proxy": "http://127.0.0.1:17880"}}:
        _fail("public_livekit_mapping_conflict", "HTTPS 8446 is not the exact voice bridge mapping")
    return f"wss://{dns}:8446"


def resolve_qa_urls(
    context: RuntimeContext,
    environment: Mapping[str, str] | None = None,
) -> QaRuntimeUrls:
    """Resolve only the expected worker URL and public browser URL, or fail closed."""
    env = os.environ if environment is None else environment
    expected = env.get("VOICE_QA_EXPECTED_LIVEKIT_URL") or env.get("LIVEKIT_URL")
    if expected:
        if not _valid_url(expected, {"ws", "wss"}):
            _fail("invalid_expected_livekit_url", "expected LiveKit URL is not a safe ws/wss origin")
    else:
        expected = _local_expected_url(context)

    public = env.get("LIVEKIT_PUBLIC_URL")
    if public:
        if not _valid_url(public, {"wss"}):
            _fail("invalid_public_livekit_url", "public LiveKit URL is not a safe wss origin")
    else:
        public = _tailnet_public_url(context)
    return QaRuntimeUrls(expected, public)
