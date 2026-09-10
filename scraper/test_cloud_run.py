"""Contract tests for the hosted no-LLM scraper entrypoint."""

from __future__ import annotations

import json
from pathlib import Path

from scraper import cloud_run


def test_cloud_run_forces_db_persistence_no_annotation_and_all_sources(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://hosted.example/job_radar")
    captured: dict[str, list[str]] = {}

    def harvest_main(argv: list[str]) -> int:
        captured["argv"] = argv
        print(json.dumps({"fetched_count": 8, "new_count": 3}))
        return 0

    receipt_path = tmp_path / "receipt.json"
    result = cloud_run.main(
        ["--receipt", str(receipt_path), "--max-pages", "2"],
        harvest_main=harvest_main,
    )

    assert result == 0
    assert "--jsonl" not in captured["argv"]
    assert "--profile" not in captured["argv"]
    assert "--no-annotate" in captured["argv"]
    assert captured["argv"][captured["argv"].index("--sources") + 1] == (
        "comeet,greenhouse,lever,workable"
    )
    assert captured["argv"][captured["argv"].index("--max-pages") + 1] == "2"

    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt == {
        "exit_code": 0,
        "result": {"fetched_count": 8, "new_count": 3},
        "run_id": "local",
        "schema_version": 1,
        "sources": ["linkedin", "comeet", "greenhouse", "lever", "workable"],
        "status": "success",
    }
    assert "postgresql://hosted.example/job_radar" not in capsys.readouterr().out


def test_cloud_run_records_failure_without_database_url(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    receipt_path = tmp_path / "receipt.json"

    result = cloud_run.main(
        ["--receipt", str(receipt_path)],
        harvest_main=lambda _argv: (_ for _ in ()).throw(AssertionError("must not run")),
    )

    assert result == 2
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["status"] == "failure"
    assert receipt["exit_code"] == 2
    assert receipt["error_code"] == "MissingDatabaseURL"
    assert "result" not in receipt


def test_cloud_run_records_harvester_failure(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://hosted.example/job_radar")
    receipt_path = tmp_path / "receipt.json"

    result = cloud_run.main(
        ["--receipt", str(receipt_path)], harvest_main=lambda _argv: 1
    )

    assert result == 1
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["status"] == "failure"
    assert receipt["error_code"] == "HarvesterFailed"


def test_cloud_run_records_exception_and_replays_output(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://hosted.example/job_radar")
    receipt_path = tmp_path / "receipt.json"

    def failing_harvest(_argv: list[str]) -> int:
        print("fetch_started")
        raise RuntimeError("boom")

    result = cloud_run.main(
        ["--receipt", str(receipt_path)], harvest_main=failing_harvest
    )

    captured = capsys.readouterr()
    assert result == 1
    assert "fetch_started" in captured.out
    assert "RuntimeError: boom" in captured.err
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["status"] == "failure"
    assert receipt["error_code"] == "HarvesterException"


def test_workflow_is_manual_bounded_hosted_and_non_overlapping() -> None:
    workflow = (
        Path(__file__).parents[1] / ".github" / "workflows" / "cloud-scrape.yml"
    ).read_text(encoding="utf-8")

    assert "workflow_dispatch:" in workflow
    assert "schedule:" not in workflow
    assert "runs-on: ubuntu-24.04" in workflow
    assert "self-hosted" not in workflow
    assert "timeout-minutes:" in workflow
    assert "cancel-in-progress: false" in workflow
    assert "DATABASE_URL: ${{ secrets.DATABASE_URL }}" in workflow
    assert "--no-annotate" not in workflow  # Enforced inside the cloud-only entrypoint.
