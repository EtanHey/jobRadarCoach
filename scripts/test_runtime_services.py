import scripts.runtime_services as subject


def test_process_identity_requires_exact_argv_tokens(monkeypatch):
    context = object()
    monkeypatch.setattr(subject, "_listener", lambda *_args: (7, "whisper-server --port 89120"))
    monkeypatch.setattr(subject, "_http", lambda *_args: True)
    probe = subject._identified_http_process(
        context, 8912, "http://127.0.0.1:8912/", "whisper-server", "--port", "8912",
    )
    assert not probe.healthy


def test_qa_mode_fails_before_any_service_start(tmp_path):
    context = type("Context", (), {
        "repo_root": tmp_path, "state_dir": tmp_path / "state", "qa_mode": True,
    })()
    services = subject.build_services(context)
    assert [service.name for service in services] == ["qa-runtime"]
    assert not services[0].probe(context).healthy
    try:
        services[0].start(context)
    except RuntimeError as error:
        assert "room-mode agent receipt" in str(error)
    else:
        raise AssertionError("QA prerequisite unexpectedly started")


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


def test_service_order_and_agent_database_env(monkeypatch, tmp_path):
    monkeypatch.setattr(subject, "_json", lambda *_args: {"DB_URL": "postgres://private"})
    monkeypatch.setenv("VOICE_STT_PORT", "8999")
    context = type("Context", (), {"repo_root": tmp_path, "state_dir": tmp_path / "state"})()
    services = subject.build_services(context)
    assert [service.name for service in services] == [
        "kubernetes", "supabase", "ollama", "kokoro", "livekit", "ui", "whisper",
        "ui-forward", "livekit-bridge", "tailscale-serve", "agent",
    ]
    assert services[-1].env["DATABASE_URL"] == "postgres://private"
    assert services[-1].env["STT_URL"] == "http://127.0.0.1:8999/inference"
