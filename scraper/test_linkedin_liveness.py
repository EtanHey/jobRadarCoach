"""Synthetic LinkedIn availability and stored-row regression tests."""

import json
from pathlib import Path
from urllib.error import HTTPError, URLError

import pytest

from scraper import liveness, recheck
from scraper.test_liveness import Response
from scraper.test_recheck import Database

URL = "https://www.linkedin.com/jobs/view/synthetic-engineer-1234567890"
GUEST = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/1234567890"
FIXTURES = Path(__file__).parent / "fixtures"


def page(name):
    return (FIXTURES / f"linkedin-synthetic-{name}.html").read_text()


@pytest.mark.parametrize("url", [URL, GUEST])
@pytest.mark.parametrize("name,phrase", [
    ("closed-no-longer", "no longer accepting applications"),
    ("closed-not-currently", "not currently accepting applications"),
])
def test_closed_pages_record_positive_phrase_and_timestamp(url, name, phrase):
    result = liveness.check_url(url, opener=lambda request, **_: Response(
        200, request.full_url, page(name)))
    assert result["alive"] is False
    assert result["liveness_reason"] == "closed-page-text"
    assert result["liveness_phrase"] == phrase
    assert result["liveness_checked_at"].endswith("Z")
    assert result["liveness_final_url"] == url


@pytest.mark.parametrize("name", ["open", "login"])
def test_open_or_login_page_with_hidden_closure_strings_stays_unknown(name):
    result = liveness.check_url(GUEST, opener=lambda request, **_: Response(
        200, request.full_url, page(name)))
    assert result["alive"] is None
    assert "liveness_phrase" not in result


@pytest.mark.parametrize("status", [404, 410, 429, 500])
@pytest.mark.parametrize("raised", [False, True])
def test_linkedin_http_failures_never_prove_closure(status, raised):
    calls = []
    def opener(request, **_):
        calls.append(request.full_url)
        if raised:
            raise HTTPError(request.full_url, status, "synthetic", {}, None)
        return Response(status, request.full_url, page("closed-no-longer"))
    result = liveness.check_url(URL, opener=opener)
    assert result["alive"] is None
    assert calls == [URL]  # Do not amplify failures with retries/fallbacks.


def test_network_failure_is_unknown_without_retry():
    calls = []
    def opener(request, **_):
        calls.append(request.full_url)
        raise URLError("synthetic offline")
    assert liveness.check_url(URL, opener=opener)["alive"] is None
    assert calls == [URL]


@pytest.mark.parametrize("final", [
    "https://www.linkedin.com/authwall", "https://www.linkedin.com/jobs/search/",
    "https://www.linkedin.com/jobs/view/another-role-9999999999",
])
def test_redirected_pages_do_not_prove_this_job_closed(final):
    result = liveness.check_url(GUEST, opener=lambda *_a, **_k: Response(
        200, final, page("closed-no-longer")))
    assert result["alive"] is None


def test_inconclusive_normal_page_uses_one_paced_guest_fallback(monkeypatch):
    events = []
    monkeypatch.setattr(liveness.time, "sleep", lambda seconds: events.append(seconds))
    def opener(request, **_):
        events.append(request.full_url)
        return Response(200, request.full_url, page(
            "open" if request.full_url == URL else "closed-not-currently"))
    result = liveness.check_url(URL, opener=opener)
    assert result["alive"] is False
    assert result["liveness_final_url"] == GUEST
    assert events == [URL, 2.0, GUEST]


def test_normal_page_auth_redirect_can_use_public_guest_evidence(monkeypatch):
    monkeypatch.setattr(liveness.time, "sleep", lambda _: None)
    def opener(request, **_):
        if request.full_url == URL:
            raise HTTPError(URL, 302, "synthetic", {"Location": "/authwall"}, None)
        return Response(200, GUEST, page("closed-no-longer"))
    assert liveness.check_url(URL, opener=opener)["alive"] is False


def test_stored_recheck_paces_requests_and_preserves_unknown_state(monkeypatch):
    events = []
    monkeypatch.setattr(recheck.time, "sleep", lambda seconds: events.append(seconds))
    closed_state = {"alive": False, "liveness_phrase": "no longer accepting applications"}
    db = Database([("closed", URL, "linkedin", "1234567890", {}),
                   ("uncertain", GUEST, "linkedin", "1234567890", closed_state)])
    def opener(request, **_):
        events.append(request.full_url)
        if request.full_url == GUEST:
            raise HTTPError(GUEST, 429, "synthetic", {}, None)
        return Response(200, URL, page("closed-no-longer"))
    monkeypatch.setattr(recheck, "pinned_open", opener)
    receipt = recheck.recheck(db, limit=2, scope="linkedin")
    assert receipt["closed"] == 1 and receipt["unknown"] == 1
    assert db.selection_params[-1] == 2
    assert events == [2.0, URL, 2.0, GUEST]
    closed = json.loads(db.writes[0][1][0])
    assert closed["alive"] is False and closed["liveness_phrase"] == closed_state["liveness_phrase"]
    assert closed["liveness_checked_at"].endswith("Z")
    uncertain = json.loads(db.writes[1][1][0])
    assert "alive" not in uncertain and "liveness_phrase" not in uncertain
    assert db.writes[1][1][-1] == json.dumps(closed_state)


def test_harvest_liveness_persists_phrase_in_existing_json_shape():
    from scraper.database import _liveness_evidence
    result = liveness.check_url(GUEST, opener=lambda request, **_: Response(
        200, request.full_url, page("closed-no-longer")))
    evidence = _liveness_evidence({"source": "linkedin", **result})
    assert evidence["alive"] is False
    assert evidence["liveness_phrase"] == "no longer accepting applications"


def test_harvest_checker_keeps_single_request_budget(monkeypatch):
    calls = []
    check = liveness.check_url
    def opener(request, **_):
        calls.append(request.full_url)
        return Response(200, request.full_url, page("open"))
    monkeypatch.setattr(liveness, "check_url", lambda url, **kwargs: check(
        url, opener=opener, **kwargs))
    monkeypatch.setattr(liveness.time, "sleep", lambda _: None)
    assert liveness.check_posting({"url": URL})["alive"] is None
    assert calls == [URL]
