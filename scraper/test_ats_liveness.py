import json
from urllib.error import HTTPError

import pytest

from scraper.ats_liveness import BoardChecker, active_ids, public_get


def posting(source="greenhouse", tenant="acme", job="1", url=None):
    return {"source": source, "external_id": f"{source}:{tenant}:{job}",
            "url": url or {"lever": f"https://jobs.lever.co/{tenant}/{job}",
                            "workable": f"https://apply.workable.com/{tenant}/j/{job}/"}.get(
                                source, f"https://job-boards.greenhouse.io/{tenant}/jobs/{job}")}


def test_membership_uses_one_complete_board_for_reposted_jobs():
    calls = []
    def fetch(url):
        calls.append(url)
        return json.dumps({"jobs": [{"id": 3}], "meta": {"total": 1}})
    checker = BoardChecker(fetch)
    assert [checker(posting(job=str(i)))["alive"] for i in (1, 2, 3)] == [False, False, True]
    assert len(calls) == 1
    assert "content=true" not in calls[0]


@pytest.mark.parametrize("body", ['{}', '{"jobs":{}}', '{"jobs":[{}],"meta":{"total":1}}',
    '{"jobs":[],"meta":{"total":2}}', '{"jobs":[{"id":true}],"meta":{"total":1}}', '<html>login</html>'])
def test_partial_or_malformed_boards_are_unknown(body):
    assert BoardChecker(lambda _: body)(posting())["alive"] is None


@pytest.mark.parametrize("status", [302, 403, 404, 410, 429, 500])
def test_board_http_failure_is_not_proof_of_job_removal(status):
    def fetch(url):
        raise HTTPError(url, status, "synthetic", {}, None)
    result = BoardChecker(fetch)(posting())
    assert result["alive"] is None and "synthetic" not in result["liveness_reason"]


def test_eu_board_and_custom_employer_url_keep_stored_identity():
    urls = []
    checker = BoardChecker(lambda url: urls.append(url) or '{"jobs":[],"meta":{"total":0}}')
    assert checker(posting(url="https://job-boards.eu.greenhouse.io/acme/jobs/1"))["alive"] is False
    assert urls == ["https://boards-api.greenhouse.io/v1/boards/acme/jobs"]
    assert BoardChecker(lambda _: '{"jobs":[],"meta":{"total":0}}')(
        posting(url="https://careers.acme.example/?gh_jid=1"))["alive"] is False


@pytest.mark.parametrize("row", [posting(tenant="../../bad"), posting(url="https://job-boards.greenhouse.io/other/jobs/1"),
    posting(source="workday"), {"source":"greenhouse","external_id":"lever:acme:1","url":""}])
def test_bad_mismatched_or_unsupported_identity_never_fetches(row):
    assert BoardChecker(lambda _: pytest.fail("no request"))(row)["alive"] is None


def test_lever_pagination_must_finish_before_any_absence_is_conclusive():
    calls = []
    def fetch(url):
        calls.append(url)
        return json.dumps([{"id": str(i)} for i in range(50)]) if "skip=0" in url else '[{"id":"last"}]'
    checker = BoardChecker(fetch)
    assert checker(posting("lever", job="last"))["alive"] is True
    assert checker(posting("lever", job="missing"))["alive"] is False
    assert len(calls) == 2 and "skip=50" in calls[1]
    assert BoardChecker(lambda _: json.dumps([{"id":str(i)} for i in range(50)]))(
        posting("lever"))["alive"] is None


def test_comeet_and_workable_use_adapter_board_identifiers():
    assert active_ids("comeet", 'COMPANY_POSITIONS_DATA = [{"uid":"A.1"}]; POSITION_DATA = null;') == {"A.1"}
    body = "# acme — All Open Positions\n| Title | Department | Location | Type | Salary | Posted | Details |\n|---|---|---|---|---|---|---|\n| Engineer | Eng | IL | Full | — | 2026-10-01 | [View](https://apply.workable.com/acme/jobs/view/ABC.md) |"
    assert active_ids("workable", body) == {"ABC"}
    assert BoardChecker(lambda _: body)(posting("workable", job="ABC"))["alive"] is True
    checker = BoardChecker(lambda _: 'COMPANY_POSITIONS_DATA = []; POSITION_DATA = null;')
    assert checker(posting("comeet", "A.1", "B.2", "https://www.comeet.com/jobs/acme/A.1/B.2"))["alive"] is False
    with pytest.raises(ValueError): active_ids("workable", "# Access denied")
    assert BoardChecker(lambda _: body.replace("/acme/", "/other/"))(
        posting("workable", job="MISSING"))["alive"] is None


def test_honest_get_transport_is_bounded_and_paced_per_host(monkeypatch):
    import scraper.ats_liveness as module
    calls, waits = [], []
    class Response:
        def __enter__(self): return self
        def __exit__(self, *_): pass
        def read(self, cap):
            assert cap == 2_000_001
            return b"{}"
    def open_request(request, **kwargs):
        calls.append(request)
        assert kwargs["timeout"] == 10
        return Response()
    monkeypatch.setattr(module, "pinned_open", open_request)
    get = public_get(clock=lambda: 10, sleep=waits.append)
    get("https://boards-api.greenhouse.io/a")
    get("https://api.lever.co/b")
    get("https://boards-api.greenhouse.io/c")
    assert waits == [1]
    assert all(r.get_method() == "GET" and "JobRadarCoach" in r.get_header("User-agent")
               and "Chrome" not in r.get_header("User-agent") for r in calls)
    monkeypatch.setattr(Response, "read", lambda _self, _cap: b"{}" + b" " * 1_999_999)
    with pytest.raises(ValueError): get("https://boards-api.greenhouse.io/oversized")
