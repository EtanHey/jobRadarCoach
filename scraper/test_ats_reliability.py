"""Synthetic persisted reliability checks against disposable PostgreSQL."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError

import psycopg
import pytest

from scraper.ats_liveness import BoardChecker
from scraper.recheck import recheck
from test_support.postgres import migrated_database


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


@pytest.fixture
def db():
    with (migrated_database(Path(__file__).parents[1] / 'supabase/migrations', through=1) as url,
          psycopg.connect(url, autocommit=True) as connection):
        connection.execute("insert into postings (source,external_id,url,title,company) values "
                           "('greenhouse','greenhouse:acme:1',"
                           "'https://job-boards.greenhouse.io/acme/jobs/1','Engineer','Synthetic')")
        connection.execute("insert into posting_status(posting_id,status) select id,'saved' from postings")
        connection.execute("insert into posting_scores(posting_id,score,brain) select id,80,'synthetic' from postings")
        yield connection

def state(db):
    return db.execute('select liveness from postings order by external_id').fetchone()[0]


def run(db, present=False, direct=None, body=None):
    Clock.current += timedelta(hours=1)
    board = BoardChecker(lambda _: body if body is not None else json.dumps(
        {'jobs': [{'id': 1}] if present else [], 'meta': {'total': int(present)}}))
    return recheck(db, board_checker=board, checker=direct or (lambda _: {
        'alive': False, 'liveness_status': 404, 'liveness_reason': 'http-404'}))


def test_single_miss_never_deactivates_or_checks_own_url(db):
    receipt = run(db, direct=lambda _: pytest.fail('first miss must not poll posting'))
    assert receipt['closed'] == 0
    assert state(db).get('alive') is not False
    assert state(db)['ats_miss_count'] == 1


def test_two_misses_and_url_gone_deactivate_preserving_status_and_score(db):
    run(db)
    assert run(db)['closed'] == 1
    assert state(db)['alive'] is False and state(db)['ats_miss_count'] == 2
    assert db.execute('select status from posting_status').fetchone() == ('saved',)
    assert db.execute('select score from posting_scores').fetchone() == (80,)


def test_persisted_gate_rejects_an_immediate_second_run(db):
    run(db)
    first = state(db)['ats_first_miss_at']
    Clock.current -= timedelta(minutes=58)  # run() adds one hour: only two minutes elapsed.
    assert run(db, direct=lambda _: pytest.fail('too early'))['closed'] == 0
    assert state(db)['ats_miss_count'] == 1 and state(db)['ats_first_miss_at'] == first
    assert state(db)['last_attempt_verdict'] == 'pending'
    Clock.current -= timedelta(minutes=17)  # 45 minutes after the original first miss.
    assert run(db)['closed'] == 1


def test_receipts_warn_once_for_steady_url_unknown_and_skip_backed_off_gets(db):
    calls = []
    direct = lambda _: calls.append(True) or {'alive': None, 'liveness_reason': 'posting-url-unknown'}
    assert run(db, direct=direct)['alerts'] == 0
    assert [run(db, direct=direct)['alerts'] for _ in range(3)] == [1, 0, 0]
    assert run(db, direct=lambda _: pytest.fail('24h backoff'))['alerts'] == 0
    assert len(calls) == 3 and state(db)['ats_url_next_check_at']


@pytest.mark.parametrize('direct', [
    {'alive': None, 'liveness_status': 200, 'liveness_reason': 'http-200-uncertain'},
    {'alive': False, 'liveness_status': 200, 'liveness_reason': 'closed-page-text'},
])
def test_two_misses_and_url_not_confirmed_gone_never_close(db, direct):
    run(db)
    assert run(db, direct=lambda _: direct)['closed'] == 0
    assert state(db).get('alive') is not False
    assert state(db)['last_attempt_verdict'] == 'unknown'
    assert state(db)['ats_alert_count'] == 1


def test_list_error_resets_consecutive_misses_and_records_unknown_alert(db):
    run(db)
    assert run(db, body='{}')['unknown'] == 1
    assert state(db).get('alive') is not False
    assert state(db)['ats_miss_count'] == 0
    assert state(db)['last_attempt_verdict'] == 'unknown'
    assert state(db)['ats_alert_count'] == 1
    assert run(db)['closed'] == 0
    assert run(db)['closed'] == 1
    # Errors cannot erase a prior conclusive closure either.
    run(db, body='{}')
    assert state(db)['alive'] is False and state(db)['ats_alert_count'] == 2


def test_reappearance_reactivates_previously_closed_row(db):
    run(db)
    run(db)
    assert run(db, present=True)['alive'] == 1
    assert state(db)['alive'] is True and state(db)['ats_miss_count'] == 0
    assert state(db)['ats_last_seen_in_list']


def test_all_ats_rows_share_a_board_even_beyond_linkedin_limit(db):
    db.execute("insert into postings(source,external_id,url,title,company) "
               "select 'greenhouse','greenhouse:acme:'||n,'https://job-boards.greenhouse.io/acme/jobs/'||n,"
               "'Engineer','Synthetic' from generate_series(2,125) n")
    calls = []
    board = BoardChecker(lambda url: calls.append(url) or json.dumps(
        {'jobs': [{'id': n} for n in range(1,126)], 'meta': {'total': 125}}))
    receipt = recheck(db, limit=1, board_checker=board,
                      checker=lambda _: pytest.fail('present IDs must not poll'))
    assert receipt['alive'] == 125 and len(calls) == 1


def test_concurrent_state_change_cannot_overwrite_reactivation(db):
    run(db)
    def direct(_):
        db.execute("update postings set liveness = '{\"alive\":true}'::jsonb")
        return {'alive': False, 'liveness_status': 410, 'liveness_reason': 'http-410'}
    assert run(db, direct=direct)['closed'] == 0
    assert state(db) == {'alive': True}


@pytest.mark.parametrize('status,location,expected', [
    (404, None, False), (410, None, False), (429, None, None),
    (302, '/acme', False), (302, '/acme?error=true', False),
    (302, '/other', None), (302, '/login', None),
    (302, 'https://foreign.example/careers', None),
])
def test_direct_check_only_status_or_bound_generic_careers_redirect(monkeypatch, status, location, expected):
    import scraper.ats_liveness as module
    url = 'https://job-boards.greenhouse.io/acme/jobs/1'
    requests = []
    def open_request(request, **_):
        requests.append(request)
        raise HTTPError(url, status, 'synthetic', {'Location': location} if location else {}, None)
    monkeypatch.setattr(module, 'pinned_open', open_request)
    result = module.check_posting_url({'source': 'greenhouse', 'external_id': 'greenhouse:acme:1', 'url': url})
    assert result['alive'] is expected
    assert len(requests) == 1 and 'JobRadarCoach' in requests[0].get_header('User-agent')


def test_hourly_workflow_is_jittered_and_cloud_does_not_duplicate_ats_runs():
    root = Path(__file__).parents[1] / '.github/workflows'
    hourly = (root / 'ats-liveness.yml').read_text()
    assert 'cron: "37 * * * *"' in hourly
    assert '--scope ats --jitter' in hourly
    assert 'group: ats-liveness' in hourly and 'cancel-in-progress: false' in hourly
    assert '--scope linkedin' in (root / 'cloud-scrape.yml').read_text()


def test_reusing_same_snapshot_does_not_supply_second_strike(db):
    board = BoardChecker(lambda _: '{"jobs":[],"meta":{"total":0}}')
    recheck(db, board_checker=board)
    assert recheck(db, board_checker=board,
                   checker=lambda _: pytest.fail('same fetch cannot provide two strikes'))['closed'] == 0
    assert state(db)['ats_miss_count'] == 1


@pytest.mark.parametrize('source,external_id,url,target', [
    ('lever', 'lever:acme:1', 'https://jobs.eu.lever.co/acme/1', '/acme'),
    ('comeet', 'comeet:A.1:B.2', 'https://www.comeet.com/jobs/acme/A.1/B.2', '/jobs/acme/A.1'),
    ('workable', 'workable:acme:ABC', 'https://apply.workable.com/acme/j/ABC/', '/acme/'),
    ('greenhouse', 'greenhouse:acme:1', 'https://careers.acme.example/jobs/1', '/careers'),
])
def test_tenant_generic_redirects_for_all_supported_sources(monkeypatch, source, external_id, url, target):
    import scraper.ats_liveness as module
    monkeypatch.setattr(module, 'pinned_open', lambda *_a, **_k: (_ for _ in ()).throw(
        HTTPError(url, 302, 'synthetic', {'Location': target}, None)))
    assert module.check_posting_url({'source': source, 'external_id': external_id, 'url': url})['alive'] is False


@pytest.mark.parametrize('url', ['http://jobs.example/1', 'https://127.0.0.1/1',
                               'https://user@jobs.example/1', 'https://jobs.example:8000/1'])
def test_unsafe_posting_url_cannot_authorize_closure(monkeypatch, url):
    import scraper.ats_liveness as module
    def open_request(request, **_):
        # The real pinned transport rejects nonpublic DNS before opening a socket.
        if '127.0.0.1' in request.full_url:
            raise OSError('nonpublic')
        pytest.fail('unsafe URL must not reach transport')
    monkeypatch.setattr(module, 'pinned_open', open_request)
    assert module.check_posting_url({'source': 'greenhouse', 'external_id': 'greenhouse:acme:1', 'url': url})['alive'] is None


def test_confirmed_inactive_row_needs_no_repeated_own_url_polling(db):
    run(db)
    run(db)
    assert state(db)['alive'] is False
    run(db, direct=lambda _: pytest.fail('confirmed closure needs only the tenant list'))
    assert state(db)['alive'] is False


def test_cli_scope_and_jitter_reach_the_persisted_writer(db, monkeypatch, tmp_path):
    import scraper.recheck as module
    calls = []
    original = module.recheck
    def check(connection, **kwargs):
        calls.append(kwargs)
        return original(connection, **kwargs, board_checker=BoardChecker(
            lambda _: '{"jobs":[{"id":1}],"meta":{"total":1}}'))
    monkeypatch.setattr(module, 'recheck', check)
    monkeypatch.setattr(module.time, 'sleep', calls.append)
    monkeypatch.setattr(module.random, 'uniform', lambda low, high: 17)
    monkeypatch.setenv('DATABASE_URL', db.info.dsn)
    receipt = tmp_path / 'receipt.json'
    assert module.main(['--scope', 'ats', '--jitter', '--receipt', str(receipt)]) == 0
    assert calls == [17, {'limit': 60, 'scope': 'ats'}]
    assert json.loads(receipt.read_text())['alive'] == 1 and state(db)['alive'] is True


@pytest.mark.parametrize('source,identity,url,body', [
    ('lever', 'lever:acme:1', 'https://jobs.lever.co/acme/1', '[]'),
    ('comeet', 'comeet:A.1:B.2', 'https://www.comeet.com/jobs/acme/A.1/B.2',
     'COMPANY_POSITIONS_DATA = []; POSITION_DATA = null;'),
    ('workable', 'workable:acme:ABC', 'https://apply.workable.com/acme/j/ABC/',
     '# acme — All Open Positions\n| Title | Department | Location | Type | Salary | Posted | Details |'),
])
@pytest.mark.parametrize('gone', [True, False])
def test_reliability_applies_to_each_supported_adapter(db, source, identity, url, body, gone):
    db.execute('update postings set source=%s, external_id=%s, url=%s', (source, identity, url))
    def check():
        Clock.current += timedelta(hours=1)
        return recheck(db, board_checker=BoardChecker(lambda _: body), checker=lambda _: {
            'alive': False if gone else None, 'liveness_status': 404 if gone else 200,
            'liveness_reason': 'http-404' if gone else 'posting-url-unknown'})
    assert check()['closed'] == 0 and state(db)['ats_miss_count'] == 1
    assert check()['closed'] == int(gone)
    assert (state(db).get('alive') is False) == gone
