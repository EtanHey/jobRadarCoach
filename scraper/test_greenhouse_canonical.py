"""Synthetic canonical own-URL confirmation through the real reliability gate."""
import json
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError

import pytest

from scraper import ats_liveness as module


class Response:
    def __init__(self): self.status = 200
    def __enter__(self): return self
    def __exit__(self, *_): return False
    def getcode(self): return self.status


def row(url='https://careers.acme.example/jobs/1', **fields):
    return {'source': 'greenhouse', 'external_id': 'greenhouse:acme:1',
            'url': url, **fields}


def transport(monkeypatch, status, location=None):
    calls = []
    monkeypatch.setattr(module.time, 'sleep', lambda seconds: None)
    def open_request(request, *, timeout):
        calls.append(request.full_url)
        assert timeout == 10 and request.get_method() == 'GET'
        assert request.get_header('User-agent') == module.USER_AGENT
        if request.full_url.startswith('https://job-boards.') and not request.full_url.endswith('/jobs/2'):
            if status == 'timeout':
                raise TimeoutError('synthetic')
            if status != 200:
                raise HTTPError(request.full_url, status, 'synthetic',
                                {'Location': location} if location else {}, None)
        return Response()
    monkeypatch.setattr(module, 'pinned_open', open_request)
    return calls


def listed_board(posting):
    board = module.BoardChecker(lambda _: json.dumps({'jobs': [{'id': 2}], 'meta': {'total': 1}}))
    assert board(posting)['alive'] is False
    return board


@pytest.mark.parametrize('url,apply_url,host', [
    ('https://careers.acme.example/jobs/1', 'https://job-boards.greenhouse.io/acme/jobs/1', 'job-boards.greenhouse.io'),
    ('https://boards.greenhouse.io/acme/jobs/1', None, 'job-boards.greenhouse.io'),
    ('https://boards.eu.greenhouse.io/acme/jobs/1', None, 'job-boards.eu.greenhouse.io'),
    ('https://careers.acme.example/jobs/1', 'https://job-boards.eu.greenhouse.io/acme/jobs/1',
     'job-boards.eu.greenhouse.io'),
    ('https://job-boards.greenhouse.io/acme/jobs/1', None, 'job-boards.greenhouse.io'),
])
@pytest.mark.parametrize('status,location', [(302, '/acme?error=true'), (404, None)])
def test_closed_canonical_confirms_custom_legacy_and_eu_rows(monkeypatch, url, apply_url, host, status, location):
    calls = transport(monkeypatch, status, location)
    posting = row(url, apply_url=apply_url)
    result = module.check_posting_url(posting, board_checker=listed_board(posting))
    assert result['alive'] is False
    assert result['liveness_status'] == status
    target = f'https://{host}/acme/jobs/1'
    assert target in calls
    assert len(calls) == (2 if url == target else 3)
    assert result['liveness_final_url'] == (f'https://{host}/acme?error=true'
                                          if status == 302 else target)


@pytest.mark.parametrize('status,location', [
    (200, None), (429, None), (403, None), (500, None), (503, None), (410, None),
    ('timeout', None), (302, None), (302, '/acme'), (301, '/acme?error=true'),
    (303, '/acme?error=true'), (307, '/acme?error=true'), (308, '/acme?error=true'),
    (302, '/other?error=true'), (302, '/acme/jobs/1?error=true'),
    (302, 'https://foreign.example/acme?error=true'),
    (302, 'https://job-boards.eu.greenhouse.io/acme?error=true'),
    (302, 'http://job-boards.greenhouse.io/acme?error=true'),
    (302, 'https://user@job-boards.greenhouse.io/acme?error=true'),
    (302, '/acme?error=true&next=login'), (302, '/acme?error=true&error=false'),
])
def test_inconclusive_canonical_never_closes(monkeypatch, status, location):
    calls = transport(monkeypatch, status, location)
    posting = row(apply_url='https://job-boards.greenhouse.io/acme/jobs/1')
    result = module.check_posting_url(posting, board_checker=listed_board(posting))
    assert result['alive'] is None
    assert len(calls) == 3  # Read Location only; never follow it.


@pytest.mark.parametrize('fields', [
    {'external_id': 'greenhouse:../acme:1'}, {'external_id': 'lever:acme:1'},
    {'apply_url': 'https://job-boards.greenhouse.io/other/jobs/1'},
    {'apply_url': 'https://jobs.lever.co/acme/1'},
])
def test_invalid_identity_never_adds_a_canonical_request(monkeypatch, fields):
    calls = transport(monkeypatch, 404)
    assert module.check_posting_url(row(**fields))['alive'] is None
    assert not any('greenhouse.io' in url for url in calls)


@pytest.mark.parametrize('source', ['lever', 'comeet', 'workable', 'ashby', 'smartrecruiters', 'workday'])
def test_canonical_fallback_is_greenhouse_only(monkeypatch, source):
    calls = transport(monkeypatch, 404)
    result = module.check_posting_url(row(source=source, external_id=f'{source}:acme:1'))
    assert result['alive'] is None
    assert calls == ['https://careers.acme.example/jobs/1']


@pytest.mark.parametrize('status,location,gone', [(302, '/acme?error=true', True),
                                                (404, None, True), (200, None, False), (429, None, False)])
def test_real_checker_respects_spacing_backoff_and_reappearance(monkeypatch, status, location, gone):
    calls = transport(monkeypatch, status, location)
    current = datetime(2026, 10, 6, tzinfo=timezone.utc)
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None): return current
    monkeypatch.setattr(module, 'datetime', Clock)
    posting = row(liveness={}, apply_url='https://job-boards.greenhouse.io/acme/jobs/1')
    board = listed_board(posting)
    def observe(present=False):
        result = {'alive': present, 'liveness_checked_at': current.isoformat(),
                  'liveness_reason': 'ats-active-list-present' if present else 'ats-active-list-absent'}
        update = module.reliability_update(posting, result, lambda p: module.check_posting_url(p, board_checker=board))
        posting['liveness'].update(update)
        return update
    assert observe()['last_attempt_verdict'] == 'pending'
    current += timedelta(minutes=44)
    assert observe()['last_attempt_verdict'] == 'pending' and not calls
    current += timedelta(minutes=1)
    update = observe()
    assert update['last_attempt_verdict'] == ('gone' if gone else 'unknown')
    assert (posting['liveness'].get('alive') is False) == gone
    if not gone:
        for _ in range(2):
            current += timedelta(hours=1)
            observe()
        count = len(calls)
        current += timedelta(hours=1)
        assert observe()['last_attempt_reason'] == 'posting-url-backoff'
        assert len(calls) == count and posting['liveness']['ats_alert_count'] == 1
    current += timedelta(hours=1)
    assert observe(present=True)['alive'] is True
    assert posting['liveness']['ats_miss_count'] == 0


@pytest.mark.parametrize('url', [
    'https://careers.acme.example/jobs/1',  # No positive regional provenance.
    'https://job-boards.eu.greenhouse.io/acme/jobs/1',  # Wrong region: live job.
    'https://job-boards.greenhouse.io/acme/jobs/1',  # Nonexistent board.
])
def test_error_redirect_without_a_listed_positive_control_never_closes(monkeypatch, url):
    transport(monkeypatch, 302, '/acme?error=true')
    assert module.check_posting_url(row(url))['alive'] is None


@pytest.mark.parametrize('control_status', [200, 302, 404, 429, 500, 'timeout'])
def test_eu_canonical_requires_successful_listed_control_and_caches_it(monkeypatch, control_status):
    calls = []
    monkeypatch.setattr(module.time, 'sleep', lambda _: None)
    def open_request(request, *, timeout):
        calls.append(request.full_url)
        status = control_status if request.full_url.endswith('/jobs/2') else 302
        if status == 'timeout':
            raise TimeoutError('synthetic control')
        if status != 200:
            raise HTTPError(request.full_url, status, 'synthetic', {'Location': '/acme?error=true'}, None)
        return Response()
    monkeypatch.setattr(module, 'pinned_open', open_request)
    board = module.BoardChecker(lambda _: json.dumps({'jobs': [{'id': 2}], 'meta': {'total': 1}}))
    for job in ('1', '3'):
        posting = row(f'https://job-boards.eu.greenhouse.io/acme/jobs/{job}', external_id=f'greenhouse:acme:{job}')
        assert board(posting)['alive'] is False
        result = module.check_posting_url(posting, board_checker=board)
        assert result['alive'] is (False if control_status == 200 else None)
    assert calls.count('https://job-boards.eu.greenhouse.io/acme/jobs/2') == 1
    fresh = module.BoardChecker(lambda _: json.dumps({'jobs': [{'id': 2}], 'meta': {'total': 1}}))
    fresh(posting)
    module.check_posting_url(posting, board_checker=fresh)
    assert calls.count('https://job-boards.eu.greenhouse.io/acme/jobs/2') == 2


@pytest.mark.parametrize('body', ['{}', '{"jobs":[],"meta":{"total":0}}',
                                '{"jobs":[{"id":2}],"meta":{"total":2}}'])
def test_missing_complete_list_or_control_cannot_authorize_closure(monkeypatch, body):
    calls = transport(monkeypatch, 302, '/acme?error=true')
    posting = row('https://job-boards.greenhouse.io/acme/jobs/1')
    board = module.BoardChecker(lambda _: body)
    board(posting)
    assert module.check_posting_url(posting, board_checker=board)['alive'] is None
    assert not any(url.endswith('/jobs/2') for url in calls)


@pytest.mark.parametrize('apply_url', [None, 'https://boards-api.greenhouse.io/v1/boards/acme/jobs'])
def test_unknown_region_cannot_use_a_valid_listed_control(monkeypatch, apply_url):
    calls = transport(monkeypatch, 302, '/acme?error=true')
    posting = row(apply_url=apply_url)
    assert module.check_posting_url(posting, board_checker=listed_board(posting))['alive'] is None
    assert calls == [posting['url']]


def test_control_on_other_region_cannot_authenticate_stored_redirect(monkeypatch):
    calls = []
    posting = row('https://job-boards.eu.greenhouse.io/acme/jobs/1',
                  apply_url='https://job-boards.greenhouse.io/acme/jobs/1')
    monkeypatch.setattr(module.time, 'sleep', lambda _: None)
    def open_request(request, **_):
        calls.append(request.full_url)
        if '.eu.greenhouse.io' in request.full_url:
            raise HTTPError(request.full_url, 302, 'synthetic', {'Location': '/acme?error=true'}, None)
        return Response()
    monkeypatch.setattr(module, 'pinned_open', open_request)
    assert module.check_posting_url(posting, board_checker=listed_board(posting))['alive'] is None
    assert calls == [posting['url'], 'https://job-boards.greenhouse.io/acme/jobs/2',
                     'https://job-boards.greenhouse.io/acme/jobs/1']


def test_malformed_stored_url_stays_unknown_without_requests(monkeypatch):
    calls = transport(monkeypatch, 404)
    assert module.check_posting_url(row('https://[invalid/jobs/1'))['alive'] is None
    assert not calls
