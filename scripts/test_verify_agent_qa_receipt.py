import json
from pathlib import Path
import sys

import pytest

import scripts.verify_agent_qa_receipt as subject


START_TIME = {"source": "ps_lstart", "value": "Mon Sep  8 12:00:00 2026"}
POD_START = "2026-09-08T12:00:00Z"


def ready_receipt():
    witness = {"count": 0, "sha256": "0" * 64}
    return {
        "schema_version": 1,
        "status": "ready",
        "process": {"pid": 4321, "start_time": START_TIME},
        "startup": {
            "voice_qa_mode": "1",
            "command_mode": "dev",
            "room_mode": True,
            "livekit_agent_name": "",
        },
        "registration": {
            "server_url": "ws://expected-livekit:7880",
            "worker_id": "worker-owned",
            "automatic": True,
            "effective_agent_name": "",
        },
        "database": {
            "transaction_read_only": True,
            "owner_tables": {
                "posting_status": witness.copy(),
                "profile": witness.copy(),
                "active_mic": witness.copy(),
            },
        },
        "reason": None,
        "written_at": "2026-09-08T12:00:01Z",
    }


def pod_list():
    return {
        "items": [{
            "metadata": {"name": "livekit-0"},
            "status": {
                "phase": "Running",
                "startTime": POD_START,
                "conditions": [{"type": "Ready", "status": "True"}],
            },
        }],
    }


def registration_logs(*worker_ids):
    lines = [f'{POD_START} {{"msg":"pod starting"}}']
    lines.extend(
        f'{POD_START} {{"msg":"worker registered","workerID":"{worker_id}",'
        f'"agentName":"","jobType":"JT_ROOM"}}'
        for worker_id in worker_ids
    )
    return "\n".join(lines)


def install_live_seams(monkeypatch, *, logs=None):
    monkeypatch.setenv("LIVEKIT_URL", "ws://expected-livekit:7880")
    monkeypatch.setattr(subject, "process_start_time", lambda _pid: START_TIME)
    monkeypatch.setattr(subject, "kubectl_json", lambda _arguments: pod_list())
    monkeypatch.setattr(
        subject,
        "kubectl_logs",
        lambda _namespace, _pod: registration_logs("worker-owned") if logs is None else logs,
    )


def assert_not_ready(code, operation):
    with pytest.raises(subject.NotReady) as caught:
        operation()
    assert caught.value.code == code


def test_valid_ready_receipt_and_pool(monkeypatch):
    install_live_seams(monkeypatch)
    receipt = subject.validate_v1_receipt(ready_receipt())
    subject.verify_pool(receipt)


@pytest.mark.parametrize("failure", ["missing", "reused"])
def test_stale_or_reused_process_is_rejected(monkeypatch, failure):
    monkeypatch.setenv("LIVEKIT_URL", "ws://expected-livekit:7880")
    if failure == "missing":
        def process_missing(_pid):
            raise subject.NotReady("process_not_live", "gone")
        monkeypatch.setattr(subject, "process_start_time", process_missing)
        code = "process_not_live"
    else:
        monkeypatch.setattr(
            subject,
            "process_start_time",
            lambda _pid: {"source": "ps_lstart", "value": "different birth"},
        )
        code = "stale_process_identity"
    assert_not_ready(code, lambda: subject.validate_v1_receipt(ready_receipt()))


def test_non_qa_receipt_is_rejected(monkeypatch):
    install_live_seams(monkeypatch)
    receipt = ready_receipt()
    receipt["startup"]["voice_qa_mode"] = "0"
    assert_not_ready("qa_mode_missing", lambda: subject.validate_v1_receipt(receipt))


def test_unknown_automatic_worker_is_rejected(monkeypatch):
    install_live_seams(
        monkeypatch,
        logs=registration_logs("worker-owned", "worker-unknown"),
    )
    receipt = subject.validate_v1_receipt(ready_receipt())
    assert_not_ready("unexpected_automatic_worker", lambda: subject.verify_pool(receipt))


@pytest.mark.parametrize(
    "logs",
    ["", '2026-09-08T12:01:00Z {"msg":"worker registered","workerID":"worker-owned"}'],
)
def test_absent_or_rotated_logs_are_rejected(monkeypatch, logs):
    install_live_seams(monkeypatch, logs=logs)
    assert_not_ready("pool_history_incomplete", subject.registration_pool)


def test_cli_v1_fails_closed_without_threshold(monkeypatch, tmp_path, capsys):
    install_live_seams(monkeypatch)
    receipt_path = tmp_path / "receipt.json"
    receipt_path.write_text(json.dumps(ready_receipt()))
    monkeypatch.setattr(
        sys,
        "argv",
        ["verify_agent_qa_receipt.py", "--require-mode", "qa", str(receipt_path)],
    )

    assert subject.main() == 1
    output = capsys.readouterr()
    assert output.out == '{"status":"NOT_READY","reason":"threshold_unknown"}\n'
    assert output.err.startswith("NOT_READY threshold_unknown ")


def test_cli_missing_receipt_is_nonzero(monkeypatch, tmp_path, capsys):
    missing = Path(tmp_path, "missing.json")
    monkeypatch.setattr(
        sys,
        "argv",
        ["verify_agent_qa_receipt.py", "--require-mode", "qa", str(missing)],
    )
    assert subject.main() == 1
    output = capsys.readouterr()
    assert output.out == '{"status":"NOT_READY","reason":"receipt_missing"}\n'
    assert output.err.startswith("NOT_READY receipt_missing ")


def test_cli_rejection_gate_has_json_stdout_and_detail(monkeypatch, tmp_path, capsys):
    install_live_seams(monkeypatch)
    receipt = ready_receipt()
    receipt["startup"]["voice_qa_mode"] = "0"
    receipt_path = tmp_path / "receipt.json"
    receipt_path.write_text(json.dumps(receipt))
    monkeypatch.setattr(
        sys,
        "argv",
        ["verify_agent_qa_receipt.py", "--require-mode", "qa", str(receipt_path)],
    )
    assert subject.main() == 1
    output = capsys.readouterr()
    assert output.out == '{"status":"NOT_READY","reason":"qa_mode_missing"}\n'
    assert output.err.startswith("NOT_READY qa_mode_missing ")
