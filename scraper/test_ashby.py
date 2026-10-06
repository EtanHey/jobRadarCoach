"""Synthetic Ashby board contracts; no owner profile or live posting fixtures."""
import importlib
import json
from datetime import date

import pytest
from scraper import cloud_run, harvest, source_registry

ACCOUNT = "synthetic-labs.example"
JOB_ID = "11111111-1111-1111-1111-111111111111"
QUERY = {"account": ACCOUNT, "company": "Synthetic Labs"}


def job(**changes):
    job_id = changes.get("id", JOB_ID)
    return {"id": job_id, "title": "Frontend Engineer", "location": "New York",
            "secondaryLocations": [{"location": "Tel Aviv", "address": {"addressCountry": "ISR"}}],
            "isListed": True, "isRemote": False,
            "descriptionPlain": "Build a synthetic frontend product. " * 10,
            "publishedAt": "2026-09-30T12:00:00Z",
            "jobUrl": f"https://jobs.ashbyhq.com/{ACCOUNT}/{job_id}",
            "applyUrl": f"https://jobs.ashbyhq.com/{ACCOUNT}/{job_id}/application", **changes}


def fetch(*jobs):
    adapter = importlib.import_module("scraper.sources.ashby")
    calls = []
    rows = adapter.fetch(QUERY, fetcher=lambda url: calls.append(url) or json.dumps({"jobs": list(jobs)}), before_request=lambda: None)
    assert calls == [f"https://api.ashbyhq.com/posting-api/job-board/{ACCOUNT}"]
    return rows


def test_ashby_maps_dates_descriptions_and_secondary_israel_location():
    row = fetch(job())[0]
    assert row["id"] == f"ashby:{ACCOUNT}:{JOB_ID}"
    assert row["company"] == "Synthetic Labs" and row["source"] == "ashby"
    assert row["posted_at"] == "2026-09-30T12:00:00Z"
    assert "Tel Aviv" in row["location"] and "Israel" in row["location"]
    assert row["jd_fetched"] is True and len(row["jd_text"]) >= 200
    assert row["alive"] is True and row["liveness_reason"] == "ashby-active-list"
    assert row["remote"] is False


@pytest.mark.parametrize("timestamp", [None, "", "invalid", "2026-09-30", "2026-09-30T12:00:00"])
def test_ashby_never_invents_publication_date(timestamp):
    assert fetch(job(publishedAt=timestamp))[0].get("posted_at") in (None, "")


def test_ashby_plain_description_falls_back_to_html():
    row = fetch(job(descriptionPlain=None, descriptionHtml="<p>Build &amp; ship.</p>"))[0]
    assert row["jd_text"] == "Build & ship."


@pytest.mark.parametrize("value", ["/application", "mailto:jobs@example.invalid", "javascript:alert(1)", 42, None,
                                 "https://[", "https://bad host/apply", "https://example.invalid:bad/apply"])
def test_invalid_apply_url_cannot_poison_the_board_response(value):
    assert fetch(job(applyUrl=value))[0]["apply_url"] is None


def test_valid_https_apply_url_is_preserved():
    assert fetch(job())[0]["apply_url"] == job()["applyUrl"]


@pytest.mark.parametrize("changes", [{"isListed": False}, {"id": ""}, {"jobUrl": ""}, {"title": ""},
    {"jobUrl": "https://example.invalid/job"}, {"jobUrl": "https://jobs.ashbyhq.com/other-account/other-job"}])
def test_ashby_skips_unlisted_or_unusable_records(changes):
    assert fetch(job(**changes)) == []


@pytest.mark.parametrize("payload", [None, [], {}, {"jobs": None}, {"jobs": "invalid"}])
def test_ashby_bad_board_is_a_failure_not_a_closed_or_empty_board(payload):
    adapter = importlib.import_module("scraper.sources.ashby")
    with pytest.raises((ValueError, RuntimeError)):
        adapter.fetch(QUERY, fetcher=lambda _: None if payload is None else json.dumps(payload), before_request=lambda: None)


def test_ashby_active_list_truth_survives_generic_liveness_budget():
    rows = fetch(job())
    def unexpected_checker(_):
        pytest.fail("active-list jobs must not consume generic liveness requests")
    assert harvest.apply_liveness_checks(rows, unexpected_checker)[0]["alive"] is True


def test_ashby_uses_shared_title_country_year_and_employer_rules():
    searches = [{"keywords": "Frontend Engineer", "location": "Israel", "recency": "r604800"}]
    row = fetch(job())[0]
    assert harvest.filter_source_postings([row], searches) == [row]
    assert harvest.filter_source_postings([dict(row, location="Berlin, Germany")], searches) == []
    assert harvest.filter_source_postings([dict(row, title="QA Engineer")], searches) == []
    assert harvest.classify_employer(row)["employer_class"] == "direct"


def test_ashby_registry_and_cloud_budget_are_wired(tmp_path, monkeypatch):
    tenant = {"source": "ashby", "identifiers": {"account": ACCOUNT}, "company": "Synthetic Labs",
              "careers_url": f"https://jobs.ashbyhq.com/{ACCOUNT}",
              "provenance": [{"kind": "synthetic", "reference": "https://example.invalid"}],
              "last_verified_at": "2026-10-04", "enabled": True}
    path = tmp_path / "registry.json"
    path.write_text(json.dumps({"schema_version": 1, "tenants": [tenant]}))
    report = source_registry.load_registry(path, as_of=date(2026, 10, 4))
    assert report.source_queries()["ashby"][0]["account"] == ACCOUNT
    assert "ashby" in cloud_run.ATS_SOURCES
    monkeypatch.setattr(cloud_run, "REGISTRY_PATH", path)
    assert cloud_run._registry_request_limits()["ashby"] >= 1
    assert ("ashbyhq.com/", "ashby") in cloud_run.URL_BUCKETS


def test_ashby_pipeline_preserves_country_title_and_seven_year_admission(tmp_path, monkeypatch):
    searches = [{"keywords": "Frontend Engineer", "location": "Israel", "recency": "r604800"}]
    monkeypatch.setattr(harvest, "load_searches", lambda _: searches)
    monkeypatch.setattr(harvest, "load_profile_contract", lambda _: {"fit_terms": {"frontend"}})
    monkeypatch.setattr(harvest, "load_source_queries", lambda *args, **kwargs: {})
    monkeypatch.setattr(harvest, "load_registry_source_queries", lambda: {"ashby": [QUERY]})
    monkeypatch.setattr(harvest, "harvest_search", lambda *args, **kwargs: ([], 0))
    records = [job(), job(id="22222222-2222-2222-2222-222222222222", title="Senior Frontend Engineer",
                        descriptionPlain="Minimum 7 years of experience required. " + "Build synthetic web software. " * 12),
               job(id="33333333-3333-3333-3333-333333333333", title="QA Engineer"),
               job(id="44444444-4444-4444-4444-444444444444", location="Berlin", secondaryLocations=[])]
    result = harvest.run_pipeline(config_path=tmp_path / "searches.json", profile_path=tmp_path / "profile.yaml",
                                  output_dir=tmp_path / "output", date_string="2026-10-04", harvested_at="2026-10-04T12:00:00Z",
                                  max_pages=1, fetcher=lambda _: json.dumps({"jobs": records}), before_request=lambda: None,
                                  enabled_sources={"ashby"}, liveness_checker=lambda _: pytest.fail("board truth must be retained"))
    assert result["source_fetch_counts"]["ashby"] == 4
    assert result["source_match_counts"]["ashby"] == 2
    assert result["source_counts"]["ashby"] == 1
    assert result["new_published_count"] == 1


@pytest.mark.parametrize(("payload", "alive"), [
    ({"jobs": [{"id": JOB_ID, "isListed": True}]}, True),
    ({"jobs": [{"id": JOB_ID, "isListed": False}]}, False),
    ({"jobs": []}, False),
    ({"jobs": [{"id": "different-job", "isListed": True}]}, False),
    ({"jobs": [{"unexpected": "schema"}]}, None),
    ({"jobs": [{"id": "", "isListed": True}]}, None),
    ({"jobs": [{"id": JOB_ID, "isListed": True}, {"id": JOB_ID, "isListed": False}]}, None),
    ({"jobs": "invalid"}, None),
])
def test_check_url_ashby_uses_active_list_only(payload, alive):
    from scraper import liveness, recheck
    from scraper.test_liveness import Response
    calls = []
    def opener(request, **kwargs):
        calls.append(request.full_url)
        assert request.get_header("User-agent") == harvest.USER_AGENT
        return Response(200, request.full_url, json.dumps(payload))
    url = job()["jobUrl"]
    assert recheck.public_job_url(url)
    result = liveness.check_url(url, opener=opener)
    assert calls == [f"https://api.ashbyhq.com/posting-api/job-board/{ACCOUNT}"]
    assert result["alive"] is alive
    assert "ashby" in recheck.ATS_SOURCES


@pytest.mark.parametrize(("status", "body", "redirect"), [(403, "denied", False), (404, "missing", False),
    (500, "failed", False), (200, "invalid-json", False), (200, '{"jobs": []}', True)])
def test_ashby_uncertain_board_never_marks_a_stored_job_closed(status, body, redirect):
    from scraper import liveness
    from scraper.test_liveness import Response
    def opener(request, **kwargs):
        return Response(status, "https://example.invalid" if redirect else request.full_url, body)
    assert liveness.check_url(job()["jobUrl"], opener=opener)["alive"] is None


def test_ashby_missing_description_retry_reads_the_public_board():
    from email.message import Message
    from scraper import description_backfill
    from scraper.test_liveness import Response
    calls = []
    def opener(request, **kwargs):
        calls.append(request.full_url)
        assert request.get_header("User-agent") == harvest.USER_AGENT
        response = Response(200, request.full_url, json.dumps({"jobs": [job()]}))
        response.headers = Message()
        return response
    assert description_backfill._fetch(job()["jobUrl"], opener=opener) == job()["descriptionPlain"].strip()
    assert calls == [f"https://api.ashbyhq.com/posting-api/job-board/{ACCOUNT}"]
    assert "'ashby'" in description_backfill.SELECT
