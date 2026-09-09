from __future__ import annotations

from datetime import datetime, timezone
import json
import os
import subprocess

import pytest

from scripts import pipeline_scheduler_status as status


NOW = datetime(2026, 9, 9, 10, 30, tzinfo=timezone.utc)


def test_failed_attempt_takes_precedence_over_older_verified_receipt():
    result = status.build_status(
        {
            "attempt_id": "23a9559b-e404-404e-8a2f-b8aa86900ba4",
            "status": "failed",
            "started_at": "2026-09-09T09:30:10.163807Z",
            "finished_at": "2026-09-09T09:30:10.164437Z",
            "failure": "UnpinnedImageReference",
        },
        {
            "run_id": "funnel-20260908t121728z-251eb555",
            "cohort_count": 94,
            "new": 31,
            "extracted": 27,
            "scored": 31,
            "failures": [{}] * 4,
        },
        now=NOW,
    )

    assert (result["state"], result["reason"]) == ("failed", "UnpinnedImageReference")
    assert result["last_verified"] == {
        "run_id": "funnel-20260908t121728z-251eb555",
        "cohort_count": 94,
        "new": 31,
        "extracted": 27,
        "scored": 31,
        "failure_count": 4,
    }


@pytest.mark.parametrize(
    ("attempt", "launchd_state", "expected"),
    [
        ({"status": "running", "started_at": "2026-09-09T10:20:00Z"},
         "loaded", ("running", None)),
        ({"status": "running", "started_at": "2026-09-09T09:00:00Z"},
         "loaded", ("stalled", "AttemptExceededRuntimeBound")),
        ({"status": "succeeded", "finished_at": "2026-09-09T03:00:00Z"},
         "loaded", ("stale", "NoRecentScheduledAttempt")),
        ({"status": "succeeded", "finished_at": "2026-09-09T10:29:00Z"},
         "unloaded", ("unknown", "LaunchAgentUnloaded")),
        ({"status": "succeeded", "finished_at": "2026-09-09T10:31:00Z"},
         "loaded", ("unknown", "AttemptTimestampInFuture")),
        ({"status": "succeeded", "finished_at": "2026-09-09T10:30:00.500000Z"},
         "loaded", ("unknown", "AttemptTimestampInFuture")),
    ],
)
def test_attempt_health_states(attempt, launchd_state, expected):
    result = status.build_status(attempt, None, now=NOW, launchd_state=launchd_state)

    assert (result["state"], result["reason"]) == expected


def test_fifo_input_is_rejected_without_opening(tmp_path):
    fifo = tmp_path / "attempt.fifo"
    os.mkfifo(fifo)

    with pytest.raises(status.StatusInputError, match="InputNotRegular"):
        status._read_object(fifo)


def test_launchctl_probe_rejects_explicitly_disabled_service(monkeypatch):
    responses = iter([
        subprocess.CompletedProcess([], 0, b"loaded", b""),
        subprocess.CompletedProcess(
            [], 0, b'"com.jobradarcoach.full-pipeline" => disabled', b"",
        ),
    ])
    monkeypatch.setattr(status, "_launchctl", lambda _argv: next(responses))

    assert status.probe_launchd() == "disabled"


def test_launchctl_probe_rejects_oversized_output(monkeypatch):
    def oversized(argv, **kwargs):
        kwargs["stdout"].write(b"x" * (status.LAUNCHCTL_OUTPUT_LIMIT + 1))
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(status.subprocess, "run", oversized)

    assert status._launchctl(["print", "gui/501/example"]) is None


def test_cli_fails_closed_when_attempt_is_missing(tmp_path, capsys):
    result = status.main([
        "--attempt", str(tmp_path / "missing.json"), "--now", "2026-09-09T10:30:00Z",
    ])
    payload = json.loads(capsys.readouterr().out)

    assert (result, payload["state"], payload["reason"]) == (1, "unknown", "InputMissing")


@pytest.mark.parametrize(
    ("attempt", "launchd_state", "reason"),
    [
        ({"status": "failed", "finished_at": "2026-09-09T09:30:11Z",
          "failure": "UnpinnedImageReference"}, "loaded", "UnpinnedImageReference"),
        ({"status": "succeeded", "finished_at": "2026-09-09T10:29:00Z"},
         "unloaded", "LaunchAgentUnloaded"),
    ],
)
def test_cli_returns_nonzero_for_unhealthy_state(
    tmp_path, capsys, monkeypatch, attempt, launchd_state, reason,
):
    attempt_path = tmp_path / "attempt.json"
    receipt_path = tmp_path / "receipt.json"
    attempt_path.write_text(json.dumps(attempt))
    receipt_path.write_text(json.dumps({"run_id": "older-run", "failures": []}))
    monkeypatch.setattr(status, "probe_launchd", lambda: launchd_state)

    result = status.main([
        "--attempt", str(attempt_path), "--receipt", str(receipt_path),
        "--now", "2026-09-09T10:30:00Z",
    ])
    rendered = capsys.readouterr().out

    assert result == 1 and "\n" not in rendered.rstrip("\n")
    assert json.loads(rendered)["reason"] == reason
