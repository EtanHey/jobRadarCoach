"""Offline tests for public listing liveness classification."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from urllib.error import HTTPError, URLError


HERE = Path(__file__).resolve().parent


def load_liveness():
    spec = importlib.util.spec_from_file_location("job_liveness", HERE / "liveness.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_harvest():
    spec = importlib.util.spec_from_file_location("job_harvest_liveness", HERE / "harvest.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Response:
    def __init__(self, status: int, url: str, body: str = "") -> None:
        self.status = status
        self.url = url
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def getcode(self) -> int:
        return self.status

    def geturl(self) -> str:
        return self.url

    def read(self, _limit: int) -> bytes:
        return self.body.encode()


def fixture(name: str) -> str:
    return (HERE / "fixtures" / name).read_text(encoding="utf-8")


def test_404_is_conclusively_dead() -> None:
    liveness = load_liveness()
    calls = []

    def opener(request, **_kwargs):
        calls.append(request.method)
        raise HTTPError(request.full_url, 404, "missing", {}, None)

    result = liveness.check_url("https://jobs.example/1", opener=opener)
    assert result["alive"] is False
    assert result["liveness_reason"] == "http-404"
    assert calls == ["GET"]


def test_200_closed_text_is_dead() -> None:
    liveness = load_liveness()

    def opener(request, **_kwargs):
        return Response(200, request.full_url, fixture("liveness-closed.html"))

    result = liveness.check_url("https://jobs.example/1", opener=opener)
    assert result["alive"] is False
    assert result["liveness_reason"] == "closed-page-text"


def test_closed_fixture_keeps_the_phrase_in_visible_body_text() -> None:
    liveness = load_liveness()
    visible = liveness._visible_text(fixture("liveness-closed.html"))
    assert "no longer accepting applications" in visible


def test_linkedin_not_currently_accepting_applications_is_dead() -> None:
    liveness = load_liveness()

    def opener(request, **_kwargs):
        return Response(
            200,
            request.full_url,
            fixture("liveness-linkedin-not-accepting.html"),
        )

    result = liveness.check_url(
        "https://www.linkedin.com/jobs/view/senior-software-engineer-4462954347",
        opener=opener,
    )
    assert result["alive"] is False
    assert result["liveness_reason"] == "closed-page-text"


def test_greenhouse_no_longer_open_phrase_is_dead() -> None:
    liveness = load_liveness()

    def opener(request, **_kwargs):
        return Response(
            200,
            request.full_url,
            fixture("liveness-greenhouse-no-longer-open.html"),
        )

    result = liveness.check_url(
        "https://job-boards.greenhouse.io/tenableinc/jobs/5114162008",
        opener=opener,
    )
    assert result["alive"] is False
    assert result["liveness_reason"] == "closed-page-text"


def test_active_page_with_hydration_blob_is_unknown_not_false_dead() -> None:
    """A LIVE ATS page whose ``__NEXT_DATA__`` i18n catalog carries the closed-job
    string must not become false-dead. Generic HTML cannot prove applyability."""

    liveness = load_liveness()
    page = fixture("liveness-active.html")
    assert "no longer accepting applications" in page, "fixture lost its i18n key"
    assert '<script id="__NEXT_DATA__"' in page, "fixture lost its hydration blob"

    def opener(request, **_kwargs):
        return Response(200, request.full_url, page)

    result = liveness.check_url("https://jobs.example/1", opener=opener)
    assert result["alive"] is None
    assert result["liveness_reason"] == "http-200-uncertain"


def test_visible_text_drops_script_and_style_content() -> None:
    liveness = load_liveness()
    body = (
        "<style>.x::after{content:'this job has expired';}</style>"
        "<script>var s = {'closed':'no longer accepting applications'};</script>"
        "<main>Apply for this role.</main>"
    )
    visible = liveness._visible_text(body)
    assert visible == "Apply for this role."
    assert "no longer accepting applications" not in visible
    assert "this job has expired" not in visible


def test_authwall_http_error_is_unknown_not_dead() -> None:
    """``urlopen`` raises on 4xx, so a real authwall never reaches the success-path
    auth check. A 403 authwall must be uncertain, and carry the real final URL."""

    liveness = load_liveness()
    authwall = "https://www.linkedin.com/authwall?trk=jobs"

    def opener(_request, **_kwargs):
        raise HTTPError(authwall, 403, "Forbidden", {}, None)

    result = liveness.check_url(
        "https://www.linkedin.com/jobs/view/full-stack-engineer-123", opener=opener
    )
    assert result["alive"] is None
    assert result["liveness_reason"] == "redirect-to-auth"
    assert result["liveness_final_url"] == authwall


def test_authwall_404_is_not_conclusively_dead() -> None:
    """404/410 stay conclusive ONLY when the final URL is not an auth path."""

    liveness = load_liveness()
    login = "https://boards.example/login"

    def opener(_request, **_kwargs):
        raise HTTPError(login, 404, "missing", {}, None)

    result = liveness.check_url("https://boards.example/jobs/1", opener=opener)
    assert result["alive"] is None
    assert result["liveness_reason"] == "redirect-to-auth"


def test_404_on_a_normal_job_path_is_still_dead() -> None:
    liveness = load_liveness()
    job_url = "https://boards.example/jobs/1"

    def opener(_request, **_kwargs):
        raise HTTPError(job_url, 404, "missing", {}, None)

    result = liveness.check_url(job_url, opener=opener)
    assert result["alive"] is False
    assert result["liveness_reason"] == "http-404"
    assert result["liveness_final_url"] == job_url


def test_non_dead_http_error_records_the_real_final_url() -> None:
    liveness = load_liveness()
    final = "https://boards.example/jobs/1?redirected=1"

    def opener(_request, **_kwargs):
        raise HTTPError(final, 500, "server error", {}, None)

    result = liveness.check_url("https://boards.example/jobs/1", opener=opener)
    assert result["alive"] is None
    assert result["liveness_reason"] == "http-500-uncertain"
    assert result["liveness_final_url"] == final


def test_redirect_from_linkedin_job_to_search_is_dead() -> None:
    liveness = load_liveness()

    def opener(_request, **_kwargs):
        return Response(200, "https://www.linkedin.com/jobs/search/")

    result = liveness.check_url(
        "https://www.linkedin.com/jobs/view/full-stack-engineer-123", opener=opener
    )
    assert result["alive"] is False
    assert result["liveness_reason"] == "redirect-to-search"


def test_redirect_from_linkedin_job_to_authwall_is_unknown() -> None:
    liveness = load_liveness()

    def opener(_request, **_kwargs):
        return Response(200, "https://www.linkedin.com/authwall?trk=jobs")

    result = liveness.check_url(
        "https://www.linkedin.com/jobs/view/full-stack-engineer-123", opener=opener
    )
    assert result["alive"] is None
    assert result["liveness_reason"] == "redirect-to-auth"


def test_greenhouse_job_redirect_to_same_board_error_is_dead() -> None:
    liveness = load_liveness()
    original = "https://job-boards.greenhouse.io/tenableinc/jobs/5114162008"
    final = "https://job-boards.greenhouse.io/tenableinc?error=true"

    def opener(_request, **_kwargs):
        return Response(200, final)

    result = liveness.check_url(original, opener=opener)
    assert result["alive"] is False
    assert result["liveness_reason"] == "greenhouse-board-error-redirect"
    assert result["liveness_final_url"] == final


def test_greenhouse_nofollow_302_location_to_same_board_error_is_dead() -> None:
    liveness = load_liveness()
    original = "https://job-boards.greenhouse.io/pagayais/jobs/7981453003"
    final = "https://job-boards.greenhouse.io/pagayais?error=true"

    def opener(_request, **_kwargs):
        raise HTTPError(original, 302, "Found", {"Location": "/pagayais?error=true"}, None)

    result = liveness.check_url(original, opener=opener)
    assert result["alive"] is False
    assert result["liveness_status"] == 302
    assert result["liveness_reason"] == "greenhouse-board-error-redirect"
    assert result["liveness_final_url"] == final


def test_greenhouse_nofollow_302_without_bound_evidence_is_unknown() -> None:
    liveness = load_liveness()
    original = "https://job-boards.greenhouse.io/tenableinc/jobs/5114162008"

    for location in (
        "https://job-boards.greenhouse.io/tenableinc",
        "https://job-boards.greenhouse.io/anotherboard?error=true",
        "https://example.com/tenableinc?error=true",
    ):
        def opener(_request, redirect=location, **_kwargs):
            raise HTTPError(original, 302, "Found", {"Location": redirect}, None)

        result = liveness.check_url(original, opener=opener)
        assert result["alive"] is None
        assert result["liveness_reason"] == "http-302-uncertain"


def test_greenhouse_board_redirect_without_complete_evidence_is_unknown() -> None:
    liveness = load_liveness()
    original = "https://job-boards.greenhouse.io/tenableinc/jobs/5114162008"

    for final in (
        "https://job-boards.greenhouse.io/tenableinc",
        "https://job-boards.greenhouse.io/anotherboard?error=true",
        "https://example.com/tenableinc?error=true",
    ):
        result = liveness.check_url(
            original, opener=lambda _request, **_kwargs: Response(200, final)
        )
        assert result["alive"] is None
        assert result["liveness_reason"] == "http-200-uncertain"


def test_generic_200_is_unknown_without_application_evidence() -> None:
    liveness = load_liveness()

    result = liveness.check_url(
        "https://jobs.example/1",
        opener=lambda request, **_kwargs: Response(
            200, request.full_url, "<main>Software engineer role</main>"
        ),
    )
    assert result["alive"] is None
    assert result["liveness_reason"] == "http-200-uncertain"


def test_network_failure_is_unknown_not_false_dead() -> None:
    liveness = load_liveness()

    def opener(request, **_kwargs):
        raise URLError(f"offline during {request.method}")

    result = liveness.check_url("https://jobs.example/1", opener=opener)
    assert result["alive"] is None
    assert result["liveness_reason"].startswith("network-uncertain:")


def test_pipeline_persists_dead_rows_but_excludes_them_from_summary(
    tmp_path: Path, monkeypatch
) -> None:
    harvest = load_harvest()
    postings = [
        {
            "id": "active",
            "title": "Full Stack Engineer",
            "company": "Comet",
            "location": "Israel",
            "url": "https://jobs.example/active",
            "posted_ago": "today",
            "jd_fetched": True,
            "jd_text": "React TypeScript Node full stack product engineering. " * 8,
        },
        {
            "id": "closed",
            "title": "Cloud Software Engineer",
            "company": "ScyllaDB",
            "location": "Israel",
            "url": "https://jobs.example/closed",
            "posted_ago": "today",
            "jd_fetched": True,
            "jd_text": "Cloud software engineering. " * 10,
        },
    ]
    monkeypatch.setattr(
        harvest,
        "harvest_search",
        lambda *_args, **_kwargs: ([dict(row) for row in postings], 0),
    )

    def checker(posting):
        alive = posting["id"] != "closed"
        return {
            "alive": alive,
            "liveness_status": 200 if alive else 404,
            "liveness_reason": "http-live" if alive else "http-404",
            "liveness_final_url": posting["url"],
            "liveness_checked_at": "2026-09-03T12:00:00Z",
        }

    result = harvest.run_pipeline(
        config_path=HERE / "searches.yaml",
        profile_path=HERE.parent / "profile.example.yaml",
        output_dir=tmp_path,
        date_string="2026-09-03",
        harvested_at="2026-09-03T12:00:00Z",
        max_pages=1,
        fetcher=lambda _url: None,
        before_request=lambda: None,
        liveness_checker=checker,
        jd_fetch_cap=0,
    )

    rows = [json.loads(line) for line in (tmp_path / "2026-09-03.jsonl").read_text().splitlines()]
    summary = (tmp_path / "latest-summary.md").read_text(encoding="utf-8")
    assert result["new_count"] == 2
    assert result["alive_count"] == 1
    assert result["dead_count"] == 1
    assert {row["id"]: row["alive"] for row in rows} == {"active": True, "closed": False}
    assert "Full Stack Engineer" in summary
    assert "Cloud Software Engineer" not in summary
    assert "Liveness: alive 1 · dead 1 · unknown 0" in summary


def test_refresh_recent_liveness_updates_only_rolling_top_20(tmp_path: Path) -> None:
    harvest = load_harvest()
    rows = [
        {
            "id": str(index),
            "title": f"Role {index}",
            "url": f"https://jobs.example/{index}",
            "score": index,
        }
        for index in range(25)
    ]
    rows[-1]["alive"] = False
    path = tmp_path / "2026-09-02.jsonl"
    path.write_text(
        "".join(json.dumps(row) + "\n" for row in rows) + "malformed-json\n",
        encoding="utf-8",
    )

    counts = harvest.refresh_recent_liveness(
        tmp_path,
        "2026-09-03",
        lambda posting: {
            "alive": True,
            "liveness_status": 200,
            "liveness_reason": "fixture",
            "liveness_final_url": posting["url"],
            "liveness_checked_at": "2026-09-03T12:00:00Z",
        },
    )

    lines = path.read_text().splitlines()
    updated = [json.loads(line) for line in lines if line != "malformed-json"]
    assert counts == {"alive": 20, "dead": 0, "unknown": 0}
    # Missing fixture row 24 must fail the test loudly.
    assert next(row for row in updated if row["id"] == "24")["alive"] is True  # skipcq: PTC-W0063
    # Missing fixture row 0 must fail the test loudly.
    assert "alive" not in next(row for row in updated if row["id"] == "0")  # skipcq: PTC-W0063
    assert lines[-1] == "malformed-json"
