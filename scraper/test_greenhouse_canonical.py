"""Synthetic canonical own-URL confirmation through the real reliability gate."""
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError

import pytest

from scraper import ats_liveness as module


class Response:
    def __enter__(self): return self
    def __exit__(self, *_): pass
    def getcode(self): return 200


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
        if request.full_url.startswith('https://job-boards.'):
            if status == 'timeout':
                raise TimeoutError('synthetic')
            if status != 200:
                raise HTTPError(request.full_url, status, 'synthetic',
                                {'Location': location} if location else {}, None)
        return Response()
    monkeypatch.setattr(module, 'pinned_open', open_request)
    return calls


@pytest.mark.parametrize('url,apply_url,host', [
    ('https://careers.acme.example/jobs/1', None, 'job-boards.greenhouse.io'),
    ('https://boards.greenhouse.io/acme/jobs/1', None, 'job-boards.greenhouse.io'),
    ('https://boards.eu.greenhouse.io/acme/jobs/1', None, 'job-boards.eu.greenhouse.io'),
    ('https://careers.acme.example/jobs/1', 'https://job-boards.eu.greenhouse.io/acme/jobs/1',
     'job-boards.eu.greenhouse.io'),
    ('https://job-boards.greenhouse.io/acme/jobs/1', None, 'job-boards.greenhouse.io'),
])
@pytest.mark.parametrize('status,location', [(302, '/acme?error=true'), (404, None)])
def test_closed_canonical_confirms_custom_legacy_and_eu_rows(monkeypatch, url, apply_url, host, status, location):
    calls = transport(monkeypatch, status, location)
    result = module.check_posting_url(row(url, apply_url=apply_url))
    assert result['alive'] is False
    assert result['liveness_status'] == status
    assert calls[-1] == f'https://{host}/acme/jobs/1'
    assert len(calls) == (1 if url == calls[-1] else 2)
    assert result['liveness_final_url'] == (f'https://{host}/acme?error=true'
                                          if status == 302 else calls[-1])


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
    result = module.check_posting_url(row())
    assert result['alive'] is None
    assert len(calls) == 2  # Read Location only; never follow it.


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
    posting = row(liveness={})
    def observe(present=False):
        result = {'alive': present, 'liveness_checked_at': current.isoformat(),
                  'liveness_reason': 'ats-active-list-present' if present else 'ats-active-list-absent'}
        update = module.reliability_update(posting, result, module.check_posting_url)
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
