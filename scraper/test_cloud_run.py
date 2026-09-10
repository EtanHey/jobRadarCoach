"""Contract tests for the hosted no-LLM scraper entrypoint."""

from __future__ import annotations

import json
from pathlib import Path
from scraper import cloud_run


def test_cloud_run_forces_db_persistence_no_annotation_and_all_sources(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://hosted.example/job_radar")
    registry = json.loads((Path(__file__).parent / "source-registry.json").read_text())
    searches = json.loads((Path(__file__).parent / "searches.yaml").read_text())["searches"]
    source_urls = {name: [] for name in cloud_run.ALL_SOURCES}
    source_urls["linkedin"] = [f"https://linkedin.com/search/{i}" for i in range(len(searches))]
    for tenant in registry["tenants"]:
        if tenant.get("enabled") is True:
            source_urls[tenant["source"]].append(tenant["careers_url"])
    attempted: list[tuple[str, tuple[object, ...]]] = []
    jd_attempted: list[str] = []
    liveness_attempted: list[object] = []
    captured: dict[str, object] = {}

    def harvest_main(argv: list[str]) -> int:
        captured["argv"] = argv
        urls = [url for source in cloud_run.ALL_SOURCES for url in source_urls[source]]
        urls += [f"https://apply.workable.com/acme/jobs/view/{i}.md" for i in range(5)]
        for url in urls:
            cloud_run.harvest.fetch_html(url)
        jd = cloud_run.harvest.load_full_jd_fetcher()
        live = cloud_run.harvest.load_liveness_checker()
        for i in range(12):
            jd(f"https://linkedin.com/jobs/view/{i}")
        for i in range(8):
            live({"url": f"https://example.test/{i}"})
        print(json.dumps({"fetched_count": 8, "new_count": 3}))
        return 0

    monkeypatch.setattr(
        cloud_run.harvest, "fetch_html",
        lambda url, **kwargs: attempted.append((url, kwargs["backoffs"])) or "body",
    )
    monkeypatch.setattr(cloud_run.harvest, "RequestPacer", lambda: lambda: None)
    monkeypatch.setattr(cloud_run.harvest, "load_full_jd_fetcher", lambda: lambda url: jd_attempted.append(url) or {})
    monkeypatch.setattr(cloud_run.harvest, "load_liveness_checker", lambda: lambda row: liveness_attempted.append(row) or {"alive": True})
    receipt_path = tmp_path / "receipt.json"
    result = cloud_run.main(
        ["--receipt", str(receipt_path), "--max-pages", "2"],
        harvest_main=harvest_main,
    )

    assert result == 0
    assert isinstance(captured["argv"], list)
    assert "--jsonl" not in captured["argv"] and "--profile" not in captured["argv"]
    assert "--no-annotate" in captured["argv"]
    assert captured["argv"][captured["argv"].index("--sources") + 1] == (
        "comeet,greenhouse,lever,workable"
    )
    assert captured["argv"][captured["argv"].index("--max-pages") + 1] == "2"
    attempted_set = {url for url, _backoffs in attempted}
    assert all(set(urls) <= attempted_set for urls in source_urls.values())
    assert all(not backoffs for _url, backoffs in attempted)
    assert len(attempted) == 48 and len(jd_attempted) == 8 and len(liveness_attempted) == 4

    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt == {
        "exit_code": 0,
        "network_request_skips": 11,
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
    assert receipt["network_request_skips"] == 0
    assert receipt["error_code"] == "MissingDatabaseURL"
    assert "result" not in receipt


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
