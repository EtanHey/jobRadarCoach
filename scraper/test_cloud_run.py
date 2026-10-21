"""Contract tests for the hosted no-LLM scraper entrypoint."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import pytest
from scraper import cloud_run


def _funnel_run(tmp_path, monkeypatch, *, tenants, jobs):
    """Exercise the real registry, adapters, filters and receipt with a fake DB writer."""
    harvest = cloud_run.harvest
    database = harvest.load_database_module()
    monkeypatch.setattr(harvest, "load_database_module", lambda: database)
    registry_dir = tmp_path / "scraper"
    registry_dir.mkdir()
    (registry_dir / "source_registry.py").write_text(
        (Path(__file__).parent / "source_registry.py").read_text()
    )
    (registry_dir / "sources").symlink_to(Path(__file__).parent / "sources")
    registry_path = registry_dir / "source-registry.json"
    registry_path.write_text(json.dumps({"schema_version": 1, "tenants": tenants}))
    monkeypatch.setattr(harvest, "SCRIPT_DIR", registry_dir)
    monkeypatch.setattr(cloud_run, "REGISTRY_PATH", registry_path)
    monkeypatch.setenv("DATABASE_URL", "postgresql://unused.test/fixture")
    monkeypatch.setattr(harvest, "RequestPacer", lambda: lambda: None)
    monkeypatch.setattr(harvest, "harvest_search", lambda *a, **kw: ([], 0))
    monkeypatch.setattr(harvest, "fetch_html", lambda url, **kw: jobs if isinstance(jobs, str) else json.dumps(jobs))
    written = []

    def writer(rows, _at):
        written.extend(rows)
        return {"observed_posting_ids": [row["id"] for row in rows],
                "inserted_posting_ids": [row["id"] for row in rows[:1]]}

    def run(_argv):
        result = harvest.run_pipeline(
            config_path=tmp_path / "unused", profile_path=tmp_path / "unused",
            output_dir=tmp_path, date_string="2026-10-22",
            harvested_at="2026-10-22T12:00:00Z", max_pages=1,
            fetcher=harvest.fetch_html, before_request=lambda: None,
            enabled_sources=set(cloud_run.ATS_SOURCES), jd_fetch_cap=0,
            profile_snapshot={"search.terms": ["Software Engineer"],
                              "candidate.open_to.geographies": ["Israel"],
                              "search.recency": "r10800", "candidate.fit_terms": [],
                              "search.location_terms": {}},
            posting_writer=writer,
        )
        print(json.dumps(result))
        return 0

    receipt_path = tmp_path / "receipt.json"
    assert cloud_run.main(["--receipt", str(receipt_path)], harvest_main=run) == 0
    return json.loads(receipt_path.read_text()), written


def _lever_tenant(*, age=1, enabled=True, account="fixture"):
    template = next(row for row in json.loads(
        (Path(__file__).parent / "source-registry.json").read_text()
    )["tenants"] if row["source"] == "lever")
    return {**template, "identifiers": {"account": account}, "enabled": enabled,
            "careers_url": f"https://jobs.lever.co/{account}",
            "last_verified_at": (datetime.now(timezone.utc).date() - timedelta(days=age)).isoformat()}


def test_receipt_warns_when_all_filtered_source(tmp_path, monkeypatch, caplog):
    receipt, written = _funnel_run(tmp_path, monkeypatch, tenants=[_lever_tenant()], jobs=[
        {"id": "rejected", "text": "Accountant", "categories": {"location": "Israel"}},
    ])
    assert not written
    # These metrics already existed on master; the missing behavior is a warning.
    assert receipt["result"]["source_fetch_counts"]["lever"] == 1
    assert receipt["result"]["source_match_counts"]["lever"] == 0
    assert any("lever" in warning and "matched=0" in warning for warning in receipt.get("warnings", []))
    assert receipt["result"]["source_warning_count"] == 1
    assert any(record.levelname == "WARNING" and "matched=0" in record.message for record in caplog.records)
    funnel = receipt["source_funnel"]["lever"]
    assert {key: funnel[key] for key in ("registered", "eligible", "requested",
                                        "filtered", "inserted_new", "updated_existing")} == {
        "registered": 1, "eligible": 1, "requested": 1,
        "filtered": 1, "inserted_new": 0, "updated_existing": 0,
    }


def test_receipt_surfaces_stale_and_disabled_boards(tmp_path, monkeypatch, caplog):
    receipt, written = _funnel_run(tmp_path, monkeypatch, tenants=[
        _lever_tenant(age=46), _lever_tenant(enabled=False, account="disabled"),
    ], jobs=[])
    assert not written
    funnel = receipt["source_funnel"]["lever"]
    assert {key: funnel[key] for key in ("registered", "eligible", "stale", "disabled", "requested")} == {
        "registered": 2, "eligible": 0, "stale": 1, "disabled": 1, "requested": 0,
    }
    assert any("lever" in warning and "eligible=0" in warning for warning in receipt["warnings"])
    assert receipt["result"]["source_warning_count"] == 1
    assert any(record.levelname == "WARNING" and "eligible=0" in record.message for record in caplog.records)


@pytest.mark.parametrize(("age", "expiring"), [(38, 0), (39, 1), (45, 1)])
def test_receipt_expiry_boundary_and_database_dispositions(tmp_path, monkeypatch, caplog, age, expiring):
    receipt, written = _funnel_run(tmp_path, monkeypatch, tenants=[_lever_tenant(age=age)], jobs=[
        {"id": str(index), "text": "Software Engineer", "categories": {"location": "Israel"},
         "descriptionPlain": "Software engineering product development. " * 8}
        for index in range(2)
    ])
    assert len(written) == 2
    funnel = receipt["source_funnel"]["lever"]
    assert receipt["result"]["source_fetch_counts"]["lever"] == 2
    assert receipt["result"]["source_match_counts"]["lever"] == 2
    assert funnel["filtered"] == 0
    assert (funnel["inserted_new"], funnel["updated_existing"]) == (1, 1)
    assert funnel["expiring_within_7d"] == expiring
    assert bool(receipt["warnings"]) == bool(expiring)
    assert any("expiring_within_7d=1" in record.message for record in caplog.records) == bool(expiring)


def test_receipt_counts_rows_filtered_before_detail_fetch(tmp_path, monkeypatch):
    tenant = _lever_tenant()
    tenant.update(source="workable", careers_url="https://apply.workable.com/fixture/")
    receipt, written = _funnel_run(tmp_path, monkeypatch, tenants=[tenant], jobs=
        "| Accountant | Finance | Israel | Full-time | — | 2026-10-21 | "
        "[View](https://apply.workable.com/fixture/jobs/view/ABC123.md) |\n"
    )
    assert not written
    funnel = receipt["source_funnel"]["workable"]
    assert (funnel["registered"], funnel["eligible"], funnel["requested"]) == (1, 1, 1)
    assert receipt["result"]["source_fetch_counts"]["workable"] == 1
    assert receipt["result"]["source_match_counts"]["workable"] == 0
    assert funnel["filtered"] == 1
    assert any("workable" in warning and "matched=0" in warning for warning in receipt["warnings"])


def _source_fixture(tmp_path: Path):
    registry = json.loads((Path(__file__).parent / "source-registry.json").read_text())
    snapshot_date = max(
        datetime.fromisoformat(row["last_verified_at"]).date()
        for row in registry["tenants"]
    ) + timedelta(days=1)
    appended = next((row.copy() for row in registry["tenants"] if row["source"] == "greenhouse"), None)
    assert appended is not None, "Greenhouse tenant required for the registry fixture"
    appended.update(
        identifiers={"board": "lateaddition"},
        company="Late Addition",
        careers_url="https://job-boards.greenhouse.io/lateaddition",
        enabled=True,
        last_verified_at=snapshot_date.isoformat(),
    )
    registry["tenants"].append(appended)
    registry_path = tmp_path / "source-registry.json"
    registry_path.write_text(json.dumps(registry))
    searches = json.loads((Path(__file__).parent / "searches.yaml").read_text())["searches"]
    source_urls = {name: [] for name in cloud_run.ALL_SOURCES}
    source_urls["linkedin"] = [f"https://linkedin.com/search/{i}" for i in range(len(searches))]
    report = cloud_run.source_registry.load_registry(registry_path, as_of=snapshot_date)
    assert not report.invalid, report.invalid
    # Independent of load_registry: enabled and verified within 45 days.
    fresh_enabled = {
        row["careers_url"] for row in registry["tenants"]
        if row["enabled"] is True
        and (snapshot_date - datetime.fromisoformat(row["last_verified_at"]).date()).days <= 45
    }
    assert {tenant["careers_url"] for tenant in report.valid} == fresh_enabled
    for tenant in report.valid:
        source_urls[tenant["source"]].append(tenant["careers_url"])
    return registry_path, source_urls, appended["careers_url"], snapshot_date


def _assert_harvest_contract(
    captured, source_urls, appended_url, attempted,
    jd_attempted, liveness_attempted, loader_openers,
):
    assert isinstance(captured["argv"], list)
    assert "--jsonl" not in captured["argv"] and "--profile" not in captured["argv"]
    assert "--no-annotate" in captured["argv"]
    assert captured["argv"][captured["argv"].index("--sources") + 1] == (
        "comeet,greenhouse,lever,workable,ashby,smartrecruiters,workday"
    )
    assert captured["argv"][captured["argv"].index("--max-pages") + 1] == "2"
    attempted_set = {url for url, _backoffs, _opener in attempted}
    assert all(set(urls) <= attempted_set for urls in source_urls.values())
    assert appended_url in attempted_set
    assert all(not backoffs and opener is cloud_run.NO_REDIRECT_OPEN for _url, backoffs, opener in attempted)
    assert loader_openers == [cloud_run.NO_REDIRECT_OPEN] * 2
    assert len(attempted) == sum(map(len, source_urls.values())) + 5
    assert len(jd_attempted) == 8 and len(liveness_attempted) == 4


@pytest.mark.parametrize("github_run_id", [None, "ci-py-fixture"])
def test_cloud_run_forces_db_persistence_no_annotation_and_all_sources(
    tmp_path: Path, monkeypatch, capsys, github_run_id
) -> None:
    registry_path, source_urls, appended_url, snapshot_date = _source_fixture(tmp_path)
    # The appended tenant is newer than the live registry. Keep coverage and
    # request budgets on its snapshot date as the registry grows and ages.
    class RegistryClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls.combine(snapshot_date, cls.min.time(), tzinfo=timezone.utc).astimezone(tz)

    monkeypatch.setattr(cloud_run.source_registry, "datetime", RegistryClock)
    if github_run_id is None:
        monkeypatch.delenv("GITHUB_RUN_ID", raising=False)
    else:
        monkeypatch.setenv("GITHUB_RUN_ID", github_run_id)
    monkeypatch.setenv("DATABASE_URL", "postgresql://hosted.example/job_radar")
    monkeypatch.setattr(cloud_run, "REGISTRY_PATH", registry_path, raising=False)
    attempted: list[tuple[str, tuple[object, ...], object]] = []
    jd_attempted: list[str] = []
    liveness_attempted: list[object] = []
    loader_openers: list[object] = []
    captured: dict[str, object] = {}

    def harvest_main(argv: list[str]) -> int:
        captured["argv"] = argv
        urls = [url for source in cloud_run.ALL_SOURCES if source != "workable" for url in source_urls[source]]
        urls += source_urls["workable"][:1]
        urls += [f"https://apply.workable.com/acme/jobs/view/{i}.md" for i in range(5)]
        urls += source_urls["workable"][1:]
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
        lambda url, **kwargs: attempted.append((url, kwargs["backoffs"], kwargs["opener"])) or "body",
    )
    monkeypatch.setattr(cloud_run.harvest, "RequestPacer", lambda: lambda: None)
    monkeypatch.setattr(cloud_run.harvest, "load_full_jd_fetcher", lambda: loader_openers.append(cloud_run.urllib_request.urlopen) or (lambda url: jd_attempted.append(url) or {}))
    monkeypatch.setattr(cloud_run.harvest, "load_liveness_checker", lambda: loader_openers.append(cloud_run.urllib_request.urlopen) or (lambda row: liveness_attempted.append(row) or {"alive": True}))
    receipt_path = tmp_path / "receipt.json"
    result = cloud_run.main(
        ["--receipt", str(receipt_path), "--max-pages", "2"],
        harvest_main=harvest_main,
    )

    assert result == 0
    _assert_harvest_contract(
        captured, source_urls, appended_url, attempted,
        jd_attempted, liveness_attempted, loader_openers,
    )

    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt == {
        "exit_code": 0,
        "network_request_skips": 8,
        "source_funnel": {},
        "warnings": [],
        "result": {"fetched_count": 8, "new_count": 3},
        "run_id": github_run_id or "local",
        "schema_version": 1,
        "sources": ["linkedin", "comeet", "greenhouse", "lever", "workable", "ashby", "smartrecruiters", "workday"],
        "status": "success",
    }
    assert "postgresql://hosted.example/job_radar" not in capsys.readouterr().out


def test_cloud_run_records_failure_without_database_url(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    receipt_path = tmp_path / "receipt.json"
    result = cloud_run.main(["--receipt", str(receipt_path)], harvest_main=lambda _argv: (_ for _ in ()).throw(AssertionError("must not run")))
    assert result == 2
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert (receipt["status"], receipt["exit_code"], receipt["network_request_skips"]) == ("failure", 2, 0)
    assert receipt["error_code"] == "MissingDatabaseURL"
    assert "result" not in receipt


def test_cloud_run_records_exception_and_replays_output(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://hosted.example/job_radar")
    receipt_path = tmp_path / "receipt.json"
    def failing_harvest(_argv: list[str]) -> int:
        print("fetch_started")
        raise RuntimeError("boom")
    result = cloud_run.main(["--receipt", str(receipt_path)], harvest_main=failing_harvest)
    captured = capsys.readouterr()
    assert result == 1
    assert "fetch_started" in captured.out and "RuntimeError: boom" in captured.err
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert (receipt["status"], receipt["error_code"]) == ("failure", "HarvesterException")


def test_workflow_is_scheduled_manual_bounded_hosted_and_non_overlapping() -> None:
    workflow = (
        Path(__file__).parents[1] / ".github" / "workflows" / "cloud-scrape.yml"
    ).read_text(encoding="utf-8")

    assert "workflow_dispatch:" in workflow
    assert 'cron: "17 */6 * * *"' in workflow
    assert "runs-on: ubuntu-24.04" in workflow
    assert "self-hosted" not in workflow
    assert "timeout-minutes:" in workflow
    assert "cancel-in-progress: false" in workflow
    assert "DATABASE_URL: ${{ secrets.DATABASE_URL }}" in workflow
    assert "--no-annotate" not in workflow  # Enforced inside the cloud-only entrypoint.
