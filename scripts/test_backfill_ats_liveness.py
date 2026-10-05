import json
from datetime import datetime, timedelta, timezone
import pytest
from scripts.backfill_ats_liveness import backfill

TAG = {"posting_id":"00000000-0000-0000-0000-000000000001", "source":"greenhouse",
       "external_id":"greenhouse:acme:1", "verdict":"gone", "checked_at":"2026-10-05T02:00:00Z"}


class Clock(datetime):
    current = datetime(2026, 10, 5, tzinfo=timezone.utc)

    @classmethod
    def now(cls, tz=None):
        return cls.current


@pytest.fixture(autouse=True)
def synthetic_clock(monkeypatch):
    import scraper.ats_liveness as module
    Clock.current = datetime(2026, 10, 5, tzinfo=timezone.utc)
    monkeypatch.setattr(module, 'datetime', Clock)


class Database:
    def __init__(self): self.calls, self.row, self.rowcount = [], (TAG["posting_id"], "https://acme.example/job", "greenhouse", TAG["external_id"], {}), 1
    def execute(self, sql, params):
        self.calls.append((sql,params))
        if sql.lstrip().startswith('update') and self.rowcount:
            self.row = (*self.row[:4], {**self.row[4], **json.loads(params[0])})
        return self
    def fetchone(self): return self.row


def test_dry_run_never_fetches_or_connects():
    assert backfill([TAG], checker=lambda _: pytest.fail("no GET"))["applied"] == 0


@pytest.mark.parametrize("alive,expected", [(False,1),(True,0),(None,0)])
def test_apply_requires_fresh_absence_and_preserves_scores_status(alive, expected):
    db = Database()
    db.row = (*db.row[:4], {"ats_miss_count": 1, "ats_first_miss_at": "2026-10-04T23:00:00+00:00"})
    receipt = backfill([TAG, {**TAG,"posting_id":"00000000-0000-0000-0000-000000000002","verdict":"unknown"}],
                       connection=db, checker=lambda _: {"alive":alive,"liveness_reason":"synthetic"},
                       url_checker=lambda _: {"alive":False,"liveness_status":404,"liveness_reason":"http-404"})
    updates = [c for c in db.calls if c[0].lstrip().startswith("update")]
    assert receipt["applied"] == expected and len(updates) == 1
    assert len(db.calls) == 2
    if updates:
        assert (json.loads(updates[0][1][0]).get("alive") is False) == bool(expected)
        assert updates[0][1][3:5] == (TAG["source"], TAG["external_id"])
        assert "posting_status" not in updates[0][0] and "posting_scores" not in updates[0][0]


def test_invalid_batch_and_changed_identity_write_nothing():
    db = Database()
    with pytest.raises(ValueError): backfill([TAG,{**TAG,"posting_id":"bad"}],connection=db,checker=lambda _: pytest.fail("no GET"))
    assert db.calls == []
    db.row = None
    assert backfill([TAG],connection=db,checker=lambda _: pytest.fail("no GET"))["applied"] == 0


def test_cli_apply_is_blocked_before_the_demo_freeze_ends(monkeypatch, tmp_path):
    import scripts.backfill_ats_liveness as module
    import psycopg
    frozen = type("Clock", (datetime,), {"now": classmethod(lambda *_: datetime(2026,10,5,tzinfo=timezone.utc))})
    monkeypatch.setattr(module, "datetime", frozen)
    monkeypatch.setenv("DATABASE_URL", "postgresql://synthetic")
    monkeypatch.setattr(psycopg, "connect", lambda *_a, **_k: pytest.fail("no connection during freeze"))
    path = tmp_path / "tags.json"
    path.write_text(json.dumps([TAG]))
    with pytest.raises(SystemExit) as error: module.main([str(path), "--apply"])
    assert error.value.code == 2


def test_concurrent_identity_change_does_not_count_a_guarded_zero_row_update():
    db = Database()
    db.rowcount = 0
    db.row = (*db.row[:4], {"ats_miss_count": 1, "ats_first_miss_at": "2026-10-04T23:00:00+00:00"})
    assert backfill([TAG], connection=db, checker=lambda _: {"alive":False},
                    url_checker=lambda _: {"alive":False,"liveness_status":410})["applied"] == 0


def test_tag_is_not_a_first_strike_or_permission_to_close():
    db = Database()
    receipt = backfill([TAG], connection=db, checker=lambda _: {'alive': False})
    assert receipt['applied'] == 0


@pytest.mark.parametrize('gone', [True, False])
def test_apply_records_two_observations_and_requires_own_url_proof(gone):
    db, urls = Database(), []
    def direct(posting):
        urls.append(posting['url'])
        return {'alive': False if gone else None, 'liveness_status': 404 if gone else 200,
                'liveness_reason': 'http-404' if gone else 'posting-url-unknown'}
    check = lambda _: {'alive': False}
    assert backfill([TAG], connection=db, checker=check, url_checker=direct)['applied'] == 0
    assert urls == [] and db.row[4]['ats_miss_count'] == 1
    Clock.current += timedelta(hours=1)
    second = backfill([TAG], connection=db, checker=check, url_checker=direct)
    assert second['applied'] == int(gone) and len(urls) == 1
    assert (db.row[4].get('alive') is False) == gone
    assert second['alerts'] == int(not gone)


def test_list_error_and_reappearance_use_the_ongoing_gate():
    db = Database()
    db.row = (*db.row[:4], {'ats_miss_count': 1})
    backfill([TAG], connection=db, checker=lambda _: {'alive': None})
    assert db.row[4]['ats_miss_count'] == 0 and db.row[4]['ats_alert_count'] == 1
    db.row = (*db.row[:4], {**db.row[4], 'alive': False})
    Clock.current += timedelta(hours=1)
    backfill([TAG], connection=db, checker=lambda _: {'alive': True})
    assert db.row[4]['alive'] is True


def test_apply_right_after_hourly_stays_pending(monkeypatch):
    import scraper.ats_liveness as module
    first = datetime(2026, 10, 5, 10, tzinfo=timezone.utc)
    frozen = type('Clock', (datetime,), {'now': classmethod(lambda *_: first + timedelta(minutes=2))})
    monkeypatch.setattr(module, 'datetime', frozen)
    db = Database()
    db.row = (*db.row[:4], {'ats_miss_count': 1, 'ats_first_miss_at': first.isoformat(),
                           'ats_last_list_checked_at': first.isoformat()})
    receipt = backfill([TAG], connection=db, checker=lambda _: {'alive': False},
                       url_checker=lambda _: pytest.fail('apply cannot supply a second strike minutes after hourly'))
    assert receipt['applied'] == 0 and receipt['observed'] == 1
    assert db.row[4]['ats_miss_count'] == 1 and db.row[4]['last_attempt_verdict'] == 'pending'
