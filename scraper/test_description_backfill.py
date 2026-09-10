import json
import gzip
from email.message import Message

import pytest

from scraper.description_backfill import MAX_BODY_BYTES, MAX_ITEMS, UPDATE, _fetch, backfill


class Database:
    def __init__(self, rows):
        self.rows = rows
        self.writes = []
    def execute(self, sql, params=()):
        if sql == UPDATE:
            self.writes.append(params)
        else:
            assert "description_fetch_attempt_at" in sql
            self.limit = params[-1]
        return self
    def fetchall(self):
        return self.rows


def test_failure_does_not_starve_later_success_and_records_attempts():
    db = Database([("first", "https://jobs.lever.co/a"),
                   ("second", "https://apply.workable.com/b")])
    complete = "Full role description\n" + "Unicode café שלום 🚀 " * 20
    def fetch(url):
        if "lever" in url:
            raise TimeoutError("secret detail")
        return complete
    assert backfill(db, limit=2, fetcher=fetch) == {
        "attempted": 2, "stored": 1, "failed": 1, "unsupported": 0}
    assert db.writes[0][0] is None
    assert json.loads(db.writes[0][3])["description_fetch_attempt_reason"] == "TimeoutError"
    assert db.writes[1][0] == complete == db.writes[1][2]


def test_update_preserves_an_existing_full_description():
    assert "%s::text is not null" in UPDATE
    assert "then %s::text else raw_jd end" in UPDATE
    assert "raw_jd is null or char_length(btrim(raw_jd)) < %s" in UPDATE


@pytest.mark.parametrize("description", [None, "complete description"])
def test_update_binds_nullable_description_as_explicit_text(description):
    db = Database([("posting", "https://jobs.lever.co/a")])
    def fetcher(_url):
        if description is None:
            raise TimeoutError
        return description
    backfill(db, fetcher=fetcher)
    assert db.writes[0][0] is description
    assert db.writes[0][2] is description
    assert UPDATE.count("%s::text") == 2


def test_work_is_bounded():
    with pytest.raises(ValueError):
        backfill(Database([]), limit=MAX_ITEMS + 1)


class Response:
    def __init__(self, body, encoding=None):
        self.body = body
        self.headers = Message()
        if encoding:
            self.headers["Content-Encoding"] = encoding
    def read(self, size):
        return self.body[:size]
    def __enter__(self):
        return self
    def __exit__(self, *_):
        return None


def test_fetch_rejects_private_target_before_opening():
    with pytest.raises(ValueError, match="unsupported-public-url"):
        _fetch("https://127.0.0.1/job", opener=lambda *_a, **_k: pytest.fail())


def test_fetch_bounds_gzip_decompression():
    body = gzip.compress(b"x" * (MAX_BODY_BYTES + 1))
    with pytest.raises(ValueError, match="body-too-large"):
        _fetch("https://jobs.linkedin.com/job/1",
               opener=lambda *_a, **_k: Response(body, "gzip"))
