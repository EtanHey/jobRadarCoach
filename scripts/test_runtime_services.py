import scripts.runtime_services as subject


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
