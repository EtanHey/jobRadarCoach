import json

import pytest

from scraper.recheck import public_job_url, recheck


class Database:
    def __init__(self, rows):
        self.rows = rows
        self.writes = []

    def execute(self, sql, params=()):
        if sql.lstrip().startswith("select"):
            assert "last_attempt_at" in sql
            self.selected_limit = params[0]
            return self
        self.writes.append((sql, params))

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
    assert receipt == {"checked": 2, "closed": 1, "unknown": 1, "unsupported": 0}
    assert json.loads(db.writes[0][1][0])["alive"] is False
    unknown = json.loads(db.writes[1][1][0])
    assert "alive" not in unknown and "liveness_reason" not in unknown
    assert unknown["last_attempt_reason"] == "http-429-uncertain"
    for sql, params in db.writes:
        assert "liveness = liveness ||" in sql
        assert "and url = %s" in sql
        assert "posting_status" not in sql and "posting_scores" not in sql
        assert len(params) == 3


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
