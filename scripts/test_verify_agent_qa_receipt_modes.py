import json
import sys

import pytest

import scripts.verify_agent_qa_receipt as subject
from scripts.test_verify_agent_qa_receipt import (
    install_live_seams,
    ready_receipt,
)


def v2_receipt(mode: str) -> dict[str, object]:
    receipt = ready_receipt()
    receipt.update(
        schema_version=2,
        mode=mode,
        worker_load_threshold=1.0,
        host_load_at_startup=0.25,
    )
    if mode == "normal":
        receipt["startup"]["voice_qa_mode"] = "0"
        receipt["database"] = None
    return receipt


@pytest.mark.parametrize("mode", ["normal", "qa"])
def test_v2_mode_validates_and_cli_reports_mode(monkeypatch, tmp_path, capsys, mode):
    install_live_seams(monkeypatch)
    monkeypatch.setattr(subject, "host_load_per_cpu", lambda: 0.5)
    receipt_path = tmp_path / f"{mode}.json"
    receipt_path.write_text(json.dumps(v2_receipt(mode)))
    monkeypatch.setattr(
        sys,
        "argv",
        ["verify_agent_qa_receipt.py", "--require-mode", mode, str(receipt_path)],
    )

    assert subject.main() == 0
    assert capsys.readouterr().out == (
        f'{{"status":"READY","mode":"{mode}","worker_id":"worker-owned"}}\n'
    )


def test_wrong_required_mode_has_stable_cli_failure(monkeypatch, tmp_path, capsys):
    receipt_path = tmp_path / "normal.json"
    receipt_path.write_text(json.dumps(v2_receipt("normal")))
    monkeypatch.setattr(
        sys,
        "argv",
        ["verify_agent_qa_receipt.py", "--require-mode", "qa", str(receipt_path)],
    )

    assert subject.main() == 1
    output = capsys.readouterr()
    assert output.out == '{"status":"NOT_READY","reason":"wrong_mode"}\n'
    assert output.err.startswith("NOT_READY wrong_mode ")


def test_live_load_is_resampled_each_verification(monkeypatch):
    install_live_seams(monkeypatch)
    samples = iter([0.25, 1.0])
    monkeypatch.setattr(subject, "host_load_per_cpu", lambda: next(samples))
    receipt = v2_receipt("normal")
    receipt["host_load_at_startup"] = 999
    validated = subject.validate_receipt(receipt, require_mode="normal")

    subject.verify_live_load(validated)
    with pytest.raises(subject.NotReady) as caught:
        subject.verify_live_load(validated)
    assert caught.value.code == "over_load_threshold"


def test_v1_has_no_provable_load_threshold():
    with pytest.raises(subject.NotReady) as caught:
        subject.verify_live_load(ready_receipt())
    assert caught.value.code == "threshold_unknown"


@pytest.mark.parametrize(
    ("pool", "reason"),
    [
        ({}, "worker_not_registered"),
        (
            {"worker-owned": {"agentName": "named", "jobType": "JT_ROOM"}},
            "wrong_dispatch_mode",
        ),
        (
            {
                "worker-owned": {"agentName": "", "jobType": "JT_ROOM"},
                "worker-other": {"agentName": "", "jobType": "JT_ROOM"},
            },
            "unexpected_automatic_worker",
        ),
    ],
)
def test_pool_must_contain_only_expected_automatic_worker(monkeypatch, pool, reason):
    monkeypatch.setattr(subject, "registration_pool", lambda: pool)
    with pytest.raises(subject.NotReady) as caught:
        subject.verify_pool(v2_receipt("normal"))
    assert caught.value.code == reason
