import scripts.runtime_services as subject
from scripts.runtime_control import Probe, RuntimeContext, Supervisor


class Sentinel:
    def __init__(self, name):
        self.name = name
        self.probes = self.starts = 0

    def probe(self, _context):
        self.probes += 1
        return Probe(True, "fixture")

    def start(self, _context):
        self.starts += 1
        return {}


def test_whisper_identity_rejects_ambiguous_or_unsafe_argv():
    valid = "whisper-server -m /tmp/model.bin --host 127.0.0.1 --port 8912 -l en".split()
    assert subject._whisper_argv(valid, 8912)
    invalid = [
        valid + ["--port", "89120"],
        [*valid[:3], "--host", "0.0.0.0", *valid[5:]],
        valid + ["--unknown", "value"],
    ]
    assert not any(subject._whisper_argv(argv, 8912) for argv in invalid)


def test_port_forward_identity_accepts_only_known_loopback_shapes():
    own = "kubectl --context orbstack -n job-radar-coach port-forward service/ui 3410:3000".split()
    installed = (
        "/opt/homebrew/bin/kubectl --context orbstack --namespace job-radar-coach "
        "port-forward --address 127.0.0.1 service/ui 3410:3000"
    ).split()
    assert subject._port_forward_argv(own) and subject._port_forward_argv(installed)
    invalid = [
        installed + ["--pod-running-timeout", "1s"],
        [*installed[:6], "--address", "0.0.0.0", *installed[8:]],
        [*installed[:5], "-n", "job-radar-coach", *installed[5:]],
    ]
    assert not any(subject._port_forward_argv(argv) for argv in invalid)


def test_qa_mode_dispatches_to_qa_stack(monkeypatch, tmp_path):
    import scripts.runtime_qa_stack as qa_stack

    context = type("Context", (), {
        "repo_root": tmp_path, "state_dir": tmp_path / "state", "qa_mode": True,
    })()
    expected = [object()]
    monkeypatch.setattr(qa_stack, "build_qa_stack", lambda received: expected if received is context else [])
    assert subject.build_services(context) is expected


def test_bridge_requires_known_argv_and_same_pid(monkeypatch, tmp_path):
    context = type("Context", (), {"repo_root": tmp_path})()
    monkeypatch.setattr(subject, "_http", lambda *_args: True)
    monkeypatch.setattr(subject, "_listener", lambda _ctx, port: (
        7 if port == 17880 else 8, "node docs.local/collabs/voice-network-bridge.cjs",
    ))
    assert not subject._bridge_probe(context).healthy
    monkeypatch.setattr(subject, "_listener", lambda *_args: (
        7, "node docs.local/collabs/voice-network-bridge.cjs",
    ))
    assert subject._bridge_probe(context).healthy


def test_normal_order_uses_room_agent_after_forwards_and_mic_gate(monkeypatch, tmp_path):
    monkeypatch.setenv("VOICE_STT_PORT", "8999")
    context = type("Context", (), {
        "repo_root": tmp_path, "state_dir": tmp_path / "state", "qa_mode": False,
    })()
    services = subject.build_services(context)
    assert [service.name for service in services] == [
        "kubernetes", "supabase", "ollama", "kokoro", "livekit", "ui", "whisper",
        "ui-forward", "livekit-bridge", "tailscale-serve", "livekit-forward", "room-ui",
        "room-agent",
    ]
    assert services[-3].command == (
        "kubectl", "--context", "orbstack", "-n", "job-radar-coach", "port-forward",
        "--address", "127.0.0.1", "svc/livekit", "7880:7880",
    )
    assert all(service.name != "agent" for service in services)


def test_mic_probe_requires_exact_200(monkeypatch, tmp_path):
    context = object()
    monkeypatch.setattr(
        subject, "_result",
        lambda *_args, **_kwargs: type("Result", (), {"returncode": 0, "stdout": "200"})(),
    )
    assert subject._mic_ui(context).healthy
    monkeypatch.setattr(
        subject, "_result",
        lambda *_args, **_kwargs: type("Result", (), {"returncode": 0, "stdout": "302"})(),
    )
    assert not subject._mic_ui(context).healthy


def test_normal_mic_failure_occurs_after_forwards_and_before_room_agent(monkeypatch, tmp_path):
    import scripts.runtime_room_agent as room_agent

    earlier = Sentinel("ui-forward")
    forward = Sentinel("livekit-forward")
    agent = Sentinel("room-agent")
    monkeypatch.setattr(subject, "_shared_services", lambda _context: [earlier])
    monkeypatch.setattr(subject, "_livekit_forward_service", lambda: forward)
    monkeypatch.setattr(subject, "_mic_ui", lambda _context: Probe(False, "fixture /mic failure"))
    monkeypatch.setattr(room_agent, "RoomAgentService", lambda: agent)
    context = RuntimeContext(tmp_path, tmp_path / "state")
    supervisor = Supervisor(context, subject._normal_services(context))
    assert supervisor.up() == 1
    assert earlier.probes == forward.probes == 1
    assert agent.probes == agent.starts == 0


def test_bridge_rejects_extra_node_flags_and_script_arguments(monkeypatch, tmp_path):
    context = type("Context", (), {"repo_root": tmp_path})()
    monkeypatch.setattr(subject, "_http", lambda *_args: True)
    for script in (
        "docs.local/collabs/voice-network-bridge.cjs",
        str(tmp_path / "scripts" / "livekit_bridge.cjs"),
    ):
        for argv in (
            f"node --inspect=0.0.0.0:9229 {script}",
            f"node --require /tmp/other.cjs {script}",
            f"node {script} --extra",
        ):
            monkeypatch.setattr(subject, "_listener", lambda *_args, command=argv: (7, command))
            assert not subject._bridge_probe(context).healthy
        monkeypatch.setattr(subject, "_listener", lambda *_args, script=script: (7, f"node {script}"))
        assert subject._bridge_probe(context).healthy


def test_ollama_requires_exact_serve_arguments(monkeypatch):
    monkeypatch.setattr(subject, "_http", lambda *_args: True)
    for argv in ("ollama serve --extra", "ollama run serve"):
        monkeypatch.setattr(subject, "_processes", lambda *_args, argv=argv: [(7, argv)])
        assert not subject._ollama(None).healthy
    monkeypatch.setattr(subject, "_processes", lambda *_args: [(7, "/opt/homebrew/bin/ollama serve")])
    assert subject._ollama(None).healthy


class Result:
    returncode = 0

    def __init__(self, stdout):
        self.stdout = stdout


def test_kokoro_requires_exact_approved_container_name(monkeypatch):
    monkeypatch.setattr(subject, "_http", lambda *_args, **_kwargs: True)
    records = [
        ('{"Names":"not-kokoro","Image":"ghcr.io/remsky/kokoro-fastapi-cpu:latest"}', False),
        ('{"Names":"impostor","Labels":"service=kokoro"}', False),
        ('malformed\n{"Names":"kokoro"}', False),
        ('null\n{"Names":"kokoro"}', False),
        ('{"Names":"kokoro"}\n{"Names":"other"}', False),
        ('{"Names":"kokoro","Image":"ghcr.io/remsky/kokoro-fastapi-cpu:latest"}', True),
    ]
    for output, expected in records:
        monkeypatch.setattr(subject, "_result", lambda *_args, output=output: Result(output))
        assert subject._kokoro(None).healthy is expected


def test_kokoro_health_probe_allows_loaded_service_ten_seconds(monkeypatch):
    calls = []

    def run(_context, command, **kwargs):
        calls.append((command, kwargs))
        if command[:2] == ("docker", "ps"):
            return Result('{"Names":"kokoro"}')
        return Result("")

    monkeypatch.setattr(subject, "_result", run)
    assert subject._kokoro(None).healthy
    command, kwargs = calls[-1]
    assert command[-3:] == ("--max-time", "10", "http://127.0.0.1:8881/v1/models")
    assert kwargs == {"timeout": 11}

    monkeypatch.setattr(subject, "_http", lambda *_args, **_kwargs: False)
    unavailable = subject._kokoro(None)
    assert not unavailable.healthy
    assert unavailable.detail == (
        "shared Kokoro identified; health endpoint timed out or returned non-success"
    )
