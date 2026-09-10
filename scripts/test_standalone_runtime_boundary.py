from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_standalone_source_excludes_embedded_voice_runtime() -> None:
    forbidden_roots = ("agent", "runtime", "k8s", "jrc", "run")
    assert [name for name in forbidden_roots if (ROOT / name).exists()] == []

    forbidden_scripts = sorted(
        path.name
        for path in (ROOT / "scripts").iterdir()
        if path.name.startswith(("runtime_", "test_runtime_"))
        or path.name
        in {
            "livekit_bridge.cjs",
            "run_batch.py",
            "test_jrc_scheduler_status.py",
            "test_livekit_bridge.py",
            "test_run_batch.py",
            "test_verify_agent_qa_receipt.py",
            "test_verify_agent_qa_receipt_modes.py",
            "verify_agent_qa_receipt.py",
        }
    )
    assert forbidden_scripts == []

    forbidden_test_support = sorted(
        path.name
        for path in (ROOT / "test_support").iterdir()
        if path.name.startswith(("runtime_", "test_runtime_"))
    )
    assert forbidden_test_support == []
