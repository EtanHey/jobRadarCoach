import json

import pytest

from scraper.recheck import public_job_url, recheck


class Database:
    def __init__(self, rows):
        # Legacy URL-check cases model the LinkedIn path; ATS cases supply identity.
        self.rows = [(*row, "linkedin", "synthetic") if len(row) == 2 else row for row in rows]
        self.rows = [(*row, {}) if len(row) == 4 else row for row in self.rows]
        self.rowcount = 1
        self.writes = []

    def execute(self, sql, params=()):
        if sql.lstrip().startswith(("select", "with")):
            assert "last_attempt_at" in sql
            self.selection_params = params
            self.selected_limit = params[-1]
            return self
        self.writes.append((sql, params))
        return self

    def fetchall(self):
        return self.rows


def test_closed_and_unknown_preserve_application_state_and_prior_evidence():
    db = Database([("closed", "https://job-boards.greenhouse.io/a/jobs/1"),
                   ("unknown", "https://il.linkedin.com/jobs/view/2")])
    def check(url):
        if "greenhouse" in url:
            return {"alive": False, "liveness_reason": "closed-page-text"}
        return {"alive": None, "liveness_reason": "http-429-uncertain"}
    receipt = recheck(db, limit=2, checker=check)
    assert receipt == {"checked": 2, "closed": 1, "alive": 0, "unknown": 1, "unsupported": 0, "alerts": 0}
    assert json.loads(db.writes[0][1][0])["alive"] is False
    unknown = json.loads(db.writes[1][1][0])
    assert "alive" not in unknown and "liveness_reason" not in unknown
    assert unknown["last_attempt_reason"] == "http-429-uncertain"
    for sql, params in db.writes:
        assert "liveness = liveness ||" in sql
        assert "and url = %s" in sql
        assert "posting_status" not in sql and "posting_scores" not in sql
        assert len(params) == 6


@pytest.mark.parametrize("url", ["http://linkedin.com/jobs/1", "https://127.0.0.1/",
    "https://linkedin.com.evil.test/a", "https://user@linkedin.com/a",
    "https://linkedin.com:8888/a", "https://linkedin.com:bad/a"])
def test_non_public_targets_never_fetched(url):
    assert not public_job_url(url)
    db = Database([("bad", url)])
    receipt = recheck(db, checker=lambda _: pytest.fail("must not fetch"))
    assert receipt["unsupported"] == 1


def test_failed_probe_does_not_block_later_jobs():
    db = Database([("one", "https://jobs.lever.co/a"),
                   ("two", "https://apply.workable.com/b")])
    def check(_):
        raise TimeoutError("not logged")
    assert recheck(db, checker=check)["unknown"] == 2
    assert len(db.writes) == 2


def test_work_is_bounded():
    with pytest.raises(ValueError):
        recheck(Database([]), limit=121)


def test_selection_binds_registered_sources_instead_of_a_sql_copy(monkeypatch):
    import scraper.recheck as module

    sources = (*module.ATS_SOURCES, "synthetic-new-ats")
    monkeypatch.setattr(module, "ATS_SOURCES", sources)
    db = Database([])
    recheck(db, scope="ats", limit=7)
    assert db.selection_params == (["linkedin", *sources], "ats", "ats", 7)
    assert "source = any(%s)" in module.SELECT_STALE


def test_default_transport_preserves_greenhouse_closed_redirect(monkeypatch):
    from urllib.error import HTTPError
    import scraper.recheck as module

    url = "https://job-boards.greenhouse.io/acme/jobs/1"
    error = HTTPError(url, 302, "redirect", {"Location": "/acme?error=true"}, None)
    monkeypatch.setattr(module, "pinned_open", lambda *_a, **_k: (_ for _ in ()).throw(error))
    db = Database([("closed", url)])
    receipt = recheck(db)
    assert receipt["closed"] == 1
    assert json.loads(db.writes[0][1][0])["liveness_reason"] == "greenhouse-board-error-redirect"


def test_ats_recheck_closes_only_absent_ids_and_binds_stored_identity():
    from scraper.ats_liveness import BoardChecker
    db = Database([("gone", "https://acme.example/jobs/1", "greenhouse", "greenhouse:acme:1"),
                   ("live", "https://acme.example/jobs/2", "greenhouse", "greenhouse:acme:2")])
    calls = []
    board = BoardChecker(lambda url: calls.append(url) or '{"jobs":[{"id":2}],"meta":{"total":1}}')
    receipt = recheck(db, board_checker=board)
    assert receipt["closed"] == 0 and receipt["alive"] == 1 and len(calls) == 1
    assert "alive" not in json.loads(db.writes[0][1][0])
    for sql, params in db.writes:
        assert "source = %s" in sql and "external_id = %s" in sql
        assert params[3:5] == ("greenhouse", f"greenhouse:acme:{1 if params[1] == 'gone' else 2}")


def test_unknown_ats_result_preserves_prior_closure_and_attempt_rotation():
    from scraper.ats_liveness import BoardChecker
    db = Database([("unknown", "https://acme.example/jobs/1", "greenhouse", "greenhouse:acme:1")])
    receipt = recheck(db, board_checker=BoardChecker(lambda _: '{}'))
    assert receipt["unknown"] == 1 and receipt["closed"] == 0
    update = json.loads(db.writes[0][1][0])
    assert "last_attempt_at" in update and "alive" not in update
