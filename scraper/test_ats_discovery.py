"""Discovery decisions use synthetic responses and never access the network."""

import json
from datetime import date

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
        return json.dumps({"name": "Other", "jobs": [{"title": "Engineer"}]})

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
