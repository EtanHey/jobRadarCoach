"""Public detail signals must be tenant-controlled before two strikes can close."""
import io
import json
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError

import pytest

from scraper import ats_liveness as ats
from scraper.recheck import recheck
from scraper.test_recheck import Database
from scraper.test_ats_reliability import db  # noqa: F401 - disposable DB fixture


def row(source='ashby'):
    if source == 'ashby':
        return {'source': source, 'external_id': 'ashby:synthetic:missing',
                'url': 'https://jobs.ashbyhq.com/synthetic/missing'}
    return {'source': source, 'external_id': 'workday:synthetic:External:Engineer_R1',
            'url': 'https://synthetic.wd5.myworkdayjobs.com/en-US/External/job/City/Engineer_R1'}


def board(source='ashby', control=True):
    if source == 'ashby':
        body = json.dumps({'jobs': [{'id': 'live', 'isListed': True}] if control else []})
    else:
        jobs = [{'title': 'Engineer', 'externalPath': '/job/City/Live_R2', 'bulletFields': ['R2']}] if control else []
        body = json.dumps({'total': len(jobs), 'jobPostings': jobs})
    check = ats.BoardChecker(lambda *_a, **_k: body)
    check(row(source))
    return check


class Response(io.BytesIO):
    def __init__(self, request, payload):
        super().__init__(json.dumps(payload).encode())
        self.url = request.full_url
    def getcode(self): return 200
    def geturl(self): return self.url


def transport(monkeypatch, source, target='gone', control='live'):
    calls = []
    def open_request(request, **kwargs):
        calls.append(request)
        assert kwargs['timeout'] == 10
        assert 'JobRadarCoach' in request.get_header('User-agent')
        if source == 'ashby':
            data = json.loads(request.data)
            identifier = data['variables']['jobPostingId']
            verdict = control if identifier == 'live' else target
            if verdict == 'gone': payload = {'data': {'jobPosting': None}}
            elif verdict == 'live': payload = {'data': {'jobPosting': {'id': identifier}}}
            elif verdict == 'mismatch': payload = {'data': {'jobPosting': {'id': 'other'}}}
            else: payload = {'data': {'jobPosting': None}, 'errors': [{'message': 'private'}]}
            return Response(request, payload)
        live = request.full_url.endswith('/Live_R2')
        verdict = control if live else target
        if verdict in ('gone', 'error'):
            raise HTTPError(request.full_url, 404 if verdict == 'gone' else 429, 'synthetic', {}, None)
        path = '/job/City/Live_R2' if live else '/job/City/Engineer_R1'
        if verdict == 'mismatch': path = '/job/City/Other_R9'
        return Response(request, {'jobPostingInfo': {'externalUrl':
            'https://synthetic.wd5.myworkdayjobs.com/External'+path}})
    monkeypatch.setattr(ats, 'pinned_open', open_request)
    monkeypatch.setattr(ats.time, 'sleep', lambda _: None)
    return calls


@pytest.mark.parametrize('source', ['ashby', 'workday'])
def test_two_spaced_misses_close_via_controlled_own_detail_and_reappearance_reopens(monkeypatch, source):
    calls = transport(monkeypatch, source)
    posting = row(source)
    state = {'alive': True, 'ats_miss_count': 1, 'ats_first_miss_at':
             (ats.datetime.now(timezone.utc)-timedelta(hours=1)).isoformat()}
    db = Database([('id', posting['url'], source, posting['external_id'], state)])
    receipt = recheck(db, board_checker=board(source))
    assert receipt['closed'] == 1
    update = json.loads(db.writes[0][1][0])
    assert update['alive'] is False and update['last_attempt_verdict'] == 'gone'
    assert len(calls) == 2
    assert source+'-detail-missing' == update['liveness_reason']
    assert update['liveness_final_url'] == calls[-1].full_url
    assert update['ats_detail_job_id'] == ('missing' if source == 'ashby' else 'r1')
    reopened = ats.reliability_update({**posting, 'liveness': {**state, **update}},
        {'alive': True, 'liveness_checked_at': datetime.now(timezone.utc).isoformat()},
        lambda _: pytest.fail('presence must not call detail'))
    assert reopened['alive'] is True and reopened['ats_miss_count'] == 0


@pytest.mark.parametrize('source', ['ashby', 'workday'])
@pytest.mark.parametrize(('target', 'control'), [('live','live'), ('error','live'),
    ('mismatch','live'), ('gone','gone'), ('gone','error'), ('gone','mismatch')])
def test_uncertain_detail_or_failed_control_preserves_availability(monkeypatch, source, target, control):
    transport(monkeypatch, source, target, control)
    result = ats.check_posting_url(row(source), board_checker=board(source))
    assert result['alive'] is None


@pytest.mark.parametrize('source', ['ashby', 'workday'])
def test_empty_board_cannot_confirm_and_control_is_cached(monkeypatch, source):
    calls = transport(monkeypatch, source)
    assert ats.check_posting_url(row(source), board_checker=board(source, False))['alive'] is None
    assert not calls
    checker = board(source)
    assert ats.check_posting_url(row(source), board_checker=checker)['alive'] is False
    assert ats.check_posting_url(row(source), board_checker=checker)['alive'] is False
    assert len(calls) == 3  # One sibling control, two target details.


def test_workday_changed_title_slug_is_same_requisition(monkeypatch):
    posting = row('workday')
    payload = {'total': 1, 'jobPostings': [{'title': 'New title',
        'externalPath': '/job/City/New-Title_R1', 'bulletFields': ['R1']}]}
    checker = ats.BoardChecker(lambda *_a, **_k: json.dumps(payload))
    assert checker(posting)['alive'] is True


@pytest.mark.parametrize('source', ['ashby', 'workday'])
@pytest.mark.parametrize('status', [301, 302, 403, 410, 429, 500])
def test_http_errors_and_redirects_are_never_closure(monkeypatch, source, status):
    original_calls = transport(monkeypatch, source)
    original_open = ats.pinned_open
    def open_request(request, **kwargs):
        is_control = (json.loads(request.data)['variables']['jobPostingId'] == 'live'
                      if source == 'ashby' else request.full_url.endswith('/Live_R2'))
        if not is_control:
            raise HTTPError(request.full_url, status, 'synthetic', {'Location': '/login'}, None)
        return original_open(request, **kwargs)
    monkeypatch.setattr(ats, 'pinned_open', open_request)
    assert ats.check_posting_url(row(source), board_checker=board(source))['alive'] is None
    assert len(original_calls) == 1


@pytest.mark.parametrize('source', ['ashby', 'workday'])
@pytest.mark.parametrize('body', [b'{}', b'<html>shell</html>', b'\xff', b' ' * 2_000_001])
def test_malformed_or_oversized_detail_stays_unknown(monkeypatch, source, body):
    transport(monkeypatch, source)
    original_open = ats.pinned_open
    def open_request(request, **kwargs):
        is_control = (json.loads(request.data)['variables']['jobPostingId'] == 'live'
                      if source == 'ashby' else request.full_url.endswith('/Live_R2'))
        if is_control:
            return original_open(request, **kwargs)
        response = Response(request, {})
        response.seek(0); response.truncate(); response.write(body); response.seek(0)
        return response
    monkeypatch.setattr(ats, 'pinned_open', open_request)
    assert ats.check_posting_url(row(source), board_checker=board(source))['alive'] is None


@pytest.mark.parametrize('url', ['https://foreign.example/synthetic/missing',
    'https://jobs.ashbyhq.com/other/missing', 'https://jobs.ashbyhq.com/synthetic/other',
    'https://user@jobs.ashbyhq.com/synthetic/missing'])
def test_foreign_or_mismatched_ashby_url_never_fetches(monkeypatch, url):
    check = board()
    monkeypatch.setattr(ats, 'pinned_open', lambda *_a, **_k: pytest.fail('unbound URL'))
    assert ats.check_posting_url({**row(), 'url': url}, board_checker=check)['alive'] is None


@pytest.mark.parametrize('source', ['ashby', 'workday'])
def test_disposable_postgres_persists_first_miss_then_controlled_closure(db, monkeypatch, source):
    class Clock(datetime):
        current = datetime(2026, 10, 11, tzinfo=timezone.utc)

        @classmethod
        def now(cls, tz=None):
            return cls.current

    monkeypatch.setattr(ats, 'datetime', Clock)
    transport(monkeypatch, source)
    posting = row(source)
    db.execute('update postings set source=%s,external_id=%s,url=%s',
               (source, posting['external_id'], posting['url']))
    assert recheck(db, board_checker=board(source))['closed'] == 0
    state = db.execute('select liveness from postings').fetchone()[0]
    assert state['ats_miss_count'] == 1 and state.get('alive') is not False
    assert recheck(db, board_checker=board(source))['closed'] == 0
    assert db.execute('select liveness from postings').fetchone()[0]['last_attempt_verdict'] == 'duplicate-snapshot'
    Clock.current += timedelta(hours=1)
    assert recheck(db, board_checker=board(source))['closed'] == 1
    assert db.execute('select liveness from postings').fetchone()[0]['alive'] is False
    assert db.execute('select status from posting_status').fetchone() == ('saved',)
    assert db.execute('select score from posting_scores').fetchone() == (80,)
