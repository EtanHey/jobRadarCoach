"""Discovery decisions use synthetic responses and never access the network."""

import json
import sys
from datetime import date, datetime, timedelta, timezone
from email.message import Message
from pathlib import Path
from unittest.mock import MagicMock
from urllib.error import HTTPError

import pytest

from scraper import ats_discovery as discovery


def test_slug_candidates_and_name_match():
    assert discovery.slugs("Acme Technologies Ltd")[:3] == [
        "acme",
        "acme-israel",
        "acmeisrael",
    ]
    assert discovery.slugs("Jeen.ai")[0] == "jeenai"
    assert discovery.company_matches("4M Analytics Ltd", "4M Analytics")
    assert not discovery.company_matches("Acme", "Acme Staffing")
    assert not discovery.company_matches("App", "App")


def test_cache_miss_expires_at_thirty_days():
    row = {"result": "miss", "slug_tried": "acme", "last_checked_at": "2026-08-24"}
    assert discovery.skip_miss(row, date(2026, 9, 22))
    assert not discovery.skip_miss(row, date(2026, 9, 23))
    row["result"] = "error"
    assert not discovery.skip_miss(row, date(2026, 9, 22))


def test_probe_requires_jobs_and_board_owned_company():
    today = date(2026, 9, 23)

    def fetch(url):
        if "/acme/jobs" in url:
            return json.dumps({"jobs": [{"id": 1, "company_name": "Wrong Co"}]})
        if "/acme-israel/jobs" in url:
            return json.dumps(
                {
                    "jobs": [
                        {
                            "id": 2,
                            "company_name": "Acme",
                            "absolute_url": "https://job-boards.eu.greenhouse.io/acme-israel/jobs/2",
                        }
                    ]
                }
            )
        return None

    result = discovery.probe("Acme", "greenhouse", fetch, today=today)
    assert result.tenant["identifiers"] == {"board": "acme-israel", "region": "eu"}
    assert result.rejected_by_name == 1
    assert result.tenant["last_verified_at"] == "2026-09-23"
    assert result.tenant["provenance"][0]["kind"] == "auto-discovery-probe"


def test_empty_and_wrong_company_do_not_enter_registry():
    def empty(_):
        return json.dumps({"jobs": []})

    def wrong(_):
        return (
            Path("scraper/fixtures/workable-myteam-jobs-2026-08-11.md")
            .read_text()
            .replace("# my team", "# Other")
        )

    assert discovery.probe("Acme", "greenhouse", empty).tenant is None
    assert discovery.probe("Acme", "workable", wrong).tenant is None


def test_merge_keeps_curated_entry_byte_equivalent():
    curated = {
        "source": "greenhouse",
        "identifiers": {"board": "acme"},
        "company": "Acme",
        "provenance": [{"kind": "curated", "reference": "x"}],
    }
    candidate = {
        **curated,
        "provenance": [{"kind": "auto-discovery-probe", "reference": "y"}],
    }
    original = {"schema_version": 1, "tenants": [curated]}
    assert discovery.merge(original, [candidate]) == original


def test_lever_uses_case_sensitive_board_and_its_own_name():
    seen = []

    def fetch(url):
        seen.append(url)
        if "/Zadara?" in url:
            return json.dumps([{"id": "one", "text": "Engineer"}])
        if url.endswith("/Zadara"):
            return '<meta property="og:title" content="Zadara jobs" />'
        return None

    result = discovery.probe("Zadara", "lever", fetch)
    assert result.tenant["identifiers"] == {"account": "Zadara"}
    assert seen[0].endswith("/Zadara?mode=json")


def test_comeet_requires_a_verified_uid_hint():
    def fetch(_):
        raise AssertionError("No URL must mean no request")

    assert discovery.probe("CHEQ", "comeet", fetch).tenant is None


def test_network_failure_is_error_and_retries_next_run():
    def broken(_):
        raise OSError("connection reset")

    result = discovery.probe("Acme", "greenhouse", broken)
    assert result.result == "error"
    assert not discovery.skip_miss(
        {"result": result.result, "last_checked_at": "2026-09-23"}, date(2026, 9, 23)
    )


def test_greenhouse_eu_region_does_not_duplicate_curated_board():
    registry = json.loads(discovery.source_registry.REGISTRY_PATH.read_text())
    candidate = discovery._candidate(
        "greenhouse",
        {"board": "guidde", "region": "eu"},
        "Guidde",
        "https://boards-api.greenhouse.io/v1/boards/guidde/jobs",
        date(2026, 9, 23),
    )
    before = len(registry["tenants"])
    assert len(discovery.merge(registry, [candidate])["tenants"]) == before


def test_429_blocks_only_that_host_and_honors_retry_after(monkeypatch):
    url = "https://apply.workable.com/acme/jobs.md"
    headers = Message()
    headers["Retry-After"] = "120"
    error = HTTPError(url, 429, "Too Many Requests", headers, None)
    fetcher = discovery.Fetcher()
    fetcher.opener.open = MagicMock(side_effect=error)
    with pytest.raises(discovery.RateLimited):
        fetcher(url)
    with pytest.raises(discovery.RateLimited):
        fetcher(url)
    assert fetcher.opener.open.call_count == 1
    assert "apply.workable.com" in fetcher.blocked_hosts

    short_headers = Message()
    short_headers["Retry-After"] = "2"
    short_error = HTTPError(url, 429, "Too Many Requests", short_headers, None)
    response = MagicMock(status=200)
    response.__enter__.return_value = response
    response.read.return_value = b"{}"
    fetcher = discovery.Fetcher()
    fetcher.opener.open = MagicMock(side_effect=[short_error, response])
    sleep = MagicMock()
    monkeypatch.setattr(discovery.time, "sleep", sleep)
    assert fetcher(url) == "{}"
    assert sleep.call_args_list[-1].args == (2,)
    assert fetcher.opener.open.call_count == 2


def test_workable_heading_and_at_least_one_adapter_job_are_required():
    fixture = Path("scraper/fixtures/workable-myteam-jobs-2026-08-11.md").read_text()
    assert discovery.probe("my team", "workable", lambda _: fixture).result == "hit"
    assert (
        discovery.probe(
            "my team", "workable", lambda _: "# my team — All Open Positions"
        ).tenant
        is None
    )


@pytest.mark.parametrize(
    ("source", "body", "hint"),
    [
        ("greenhouse", '{"jobs":[{"company_name":"Acme"}]}', ""),
        ("lever", "[]", ""),
        ("workable", "# Acme — All Open Positions", ""),
        (
            "comeet",
            "<script>COMPANY_POSITIONS_DATA = []; POSITION_DATA = {};</script>",
            "https://www.comeet.com/jobs/acme/CA.001",
        ),
    ],
)
def test_matching_but_empty_board_never_enters_registry(source, body, hint):
    assert (
        discovery.probe("Acme", source, lambda _: body, comeet_url=hint).tenant is None
    )


def test_main_persists_error_and_skips_only_fresh_miss(tmp_path, monkeypatch):
    today = datetime.now(timezone.utc).date()
    names, cache, output = (tmp_path / name for name in ("names", "cache", "output"))
    names.write_text("Acme\nAcme Ltd\nBeta\n")
    cache.write_text(
        json.dumps(
            {
                f"acme|{ats}": {
                    "result": result,
                    "slug_tried": "acme",
                    "last_checked_at": checked,
                }
                for ats, result, checked in (
                    ("greenhouse", "miss", today.isoformat()),
                    ("lever", "miss", (today - timedelta(days=30)).isoformat()),
                    ("workable", "error", today.isoformat()),
                )
            }
        )
    )
    calls = []

    def stub(name, source, fetch, *, today, comeet_url):
        calls.append((name, source))
        if name == "Acme" and source == "workable":
            fetch.blocked_hosts.add(discovery.HOSTS["workable"])
        if name in ("Acme", "Acme Ltd") and source == "lever":
            tenant = discovery._candidate(
                source,
                {"account": "acme"},
                name,
                "https://api.lever.co/v0/postings/acme?mode=json",
                today,
            )
            return discovery.ProbeResult(tenant=tenant, result="hit")
        if name == "Beta" and source == "greenhouse":
            tenant = discovery._candidate(
                source,
                {"board": "beta"},
                name,
                "https://boards-api.greenhouse.io/v1/boards/beta/jobs",
                today,
            )
            return discovery.ProbeResult(tenant=tenant, result="hit", slug_tried="beta")
        return discovery.ProbeResult(result="error" if source == "workable" else "miss")

    monkeypatch.setattr(discovery, "probe", stub)
    name_reads = MagicMock(wraps=discovery._names)
    monkeypatch.setattr(discovery, "_names", name_reads)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "ats_discovery",
            "--names",
            str(names),
            "--cache",
            str(cache),
            "--out",
            str(output),
        ],
    )
    discovery.main()
    assert name_reads.call_count == 1
    assert ("Acme", "greenhouse") not in calls
    assert ("Acme", "lever") in calls and ("Acme", "workable") in calls
    assert ("Beta", "workable") not in calls
    assert [row["company"] for row in json.loads(output.read_text())["tenants"]] == [
        "Acme",
        "Beta",
    ]
    assert json.loads(cache.read_text())["acme|workable"]["result"] == "error"
    calls.clear()
    discovery.main()
    assert name_reads.call_count == 2
    assert ("Acme", "workable") in calls


def test_cache_write_interruption_preserves_previous_json(tmp_path, monkeypatch):
    cache = tmp_path / "cache.json"
    cache.write_text('{"previous": true}')

    def interrupted(*_):
        raise OSError("interrupted before replace")

    monkeypatch.setattr(discovery.os, "replace", interrupted)
    with pytest.raises(OSError):
        discovery._save_cache(cache, {"next": True})
    assert json.loads(cache.read_text()) == {"previous": True}


def test_lever_truncated_utf8_character_decodes_safely():
    fetcher = discovery.Fetcher()
    response = MagicMock(status=200)
    response.__enter__.return_value = response
    response.read.return_value = b"a" * 65_535 + "א".encode()[:1]
    fetcher.opener.open = MagicMock(return_value=response)
    assert fetcher("https://jobs.lever.co/acme").startswith("a" * 65_535)


def test_fetcher_paces_retries_once_and_rejects_redirects(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(discovery.time, "monotonic", lambda: now[0])

    def sleep(seconds):
        now[0] += seconds

    monkeypatch.setattr(discovery.time, "sleep", sleep)
    fetcher = discovery.Fetcher()
    response = MagicMock(status=200)
    response.__enter__.return_value = response
    response.read.return_value = b"{}"
    fetcher.opener.open = MagicMock(return_value=response)
    url = "https://boards-api.greenhouse.io/v1/boards/acme/jobs"
    fetcher(url)
    fetcher(url)
    assert now[0] == 100.5
    assert fetcher.opener.open.call_count == 2
    request = fetcher.opener.open.call_args.args[0]
    assert request.get_header("User-agent") == (
        "Mozilla/5.0 (compatible; jobRadarCoach/1.0; +https://etanheyman.com)"
    )
    assert any(
        isinstance(h, discovery._NoRedirect)
        for h in discovery.Fetcher().opener.handlers
    )
    with pytest.raises(ValueError):
        fetcher("https://example.com/private")
    assert fetcher.opener.open.call_count == 2
    fetcher.opener.open = MagicMock(
        side_effect=HTTPError(url, 503, "Down", Message(), None)
    )
    with pytest.raises(HTTPError):
        fetcher(url)
    assert fetcher.opener.open.call_count == 2
