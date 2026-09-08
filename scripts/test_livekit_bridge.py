import json
import os
from pathlib import Path
import signal
import socket
import socketserver
import subprocess
import threading
import time


class EchoHandler(socketserver.BaseRequestHandler):
    def handle(self):
        while payload := self.request.recv(4096):
            self.request.sendall(payload)


def _echo_server():
    server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), EchoHandler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def _unused_port():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def _wait_for_port(port, process):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise AssertionError(f"bridge exited early: {process.stderr.read()}")
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                return
        except OSError:
            time.sleep(0.02)
    raise AssertionError(f"bridge did not listen on {port}")


def _open_client(port, payload):
    client = socket.create_connection(("127.0.0.1", port), timeout=1)
    client.sendall(payload)
    assert client.recv(len(payload)) == payload
    return client


def test_real_bridge_relays_both_routes_and_sigterm_releases_sockets(tmp_path):
    upstreams = [_echo_server(), _echo_server()]
    local_ports = [_unused_port(), _unused_port()]
    while local_ports[1] == local_ports[0]:
        local_ports[1] = _unused_port()
    fake_kubectl = tmp_path / "kubectl"
    expected = ["--context", "test-context", "-n", "test-ns", "get", "service/livekit", "-o", "json"]
    fake_kubectl.write_text(
        "#!/usr/bin/env python3\nimport json,sys\n"
        f"assert sys.argv[1:] == {expected!r}\n"
        f"print(json.dumps({json.dumps({'spec': {'clusterIP': '127.0.0.1'}})}))\n"
    )
    fake_kubectl.chmod(0o700)
    env = {
        **os.environ,
        "KUBECTL": str(fake_kubectl), "KUBE_CONTEXT": "test-context", "KUBE_NAMESPACE": "test-ns",
        "VOICE_BRIDGE_HTTP_PORT": str(local_ports[0]), "VOICE_BRIDGE_RTC_PORT": str(local_ports[1]),
        "LIVEKIT_SERVICE_HTTP_PORT": str(upstreams[0].server_address[1]),
        "LIVEKIT_SERVICE_RTC_PORT": str(upstreams[1].server_address[1]),
    }
    bridge = Path(__file__).with_name("livekit_bridge.cjs")
    process = subprocess.Popen(
        ["node", str(bridge)], env=env, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    clients = []
    try:
        for port in local_ports:
            _wait_for_port(port, process)
        clients = [
            _open_client(local_ports[0], b"signaling"),
            _open_client(local_ports[1], b"rtc-data"),
        ]
        process.send_signal(signal.SIGTERM)
        for client in clients:
            client.settimeout(1)
            try:
                closed = client.recv(1) == b""
            except ConnectionError:
                closed = True
            assert closed, "active relay stayed open after SIGTERM"
        assert process.wait(timeout=5) == 0
        for client in clients:
            client.close()
        clients.clear()
        for port in local_ports:
            with socket.socket() as listener:
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                listener.bind(("127.0.0.1", port))
    finally:
        for client in clients:
            client.close()
        if process.poll() is None:
            process.kill()
            process.wait(timeout=2)
        for server in upstreams:
            server.shutdown()
            server.server_close()
