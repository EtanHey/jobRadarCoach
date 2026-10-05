"""Synthetic board snapshots: all pages precede membership and persisted strikes."""
import json
from datetime import timedelta
from urllib.error import HTTPError

import pytest

from scraper.ats_liveness import BoardChecker, board_identity
from scraper.recheck import recheck
from scraper.test_ats_reliability import Clock, state
pytest_plugins = ['scraper.test_ats_reliability']


SOURCES = ('ashby', 'smartrecruiters', 'workday')


def posting(source, job='1', site='External', cluster='wd5'):
    if source == 'workday':
        return {'source': source, 'external_id': f'workday:synthetic:{site}:Engineer_R{job}',
                'url': f'https://synthetic.{cluster}.myworkdayjobs.com/{site}/job/Israel/Engineer_R{job}'}
    host = 'jobs.ashbyhq.com' if source == 'ashby' else 'jobs.smartrecruiters.com'
    return {'source': source, 'external_id': f'{source}:synthetic:{job}',
            'url': f'https://{host}/synthetic/{job}'}


def page(source, ids, total=None, offset=0):
    total = len(ids) if total is None else total
    if source == 'ashby':
        return json.dumps({'jobs': [{'id': str(i), 'isListed': True} for i in ids]})
    if source == 'smartrecruiters':
        return json.dumps({'content': [{'id': str(i), 'name': 'Engineer',
                           'company': {'identifier': 'synthetic'}} for i in ids],
                           'totalFound': total, 'offset': offset, 'limit': 100})
    return json.dumps({'jobPostings': [{'title': 'Engineer', 'externalPath': f'/job/Israel/Engineer_R{i}',
                       'bulletFields': [f'R{i}']} for i in ids], 'total': total})


@pytest.mark.parametrize('source', SOURCES)
def test_complete_snapshot_is_shared_and_unfiltered(source):
    calls = []
    def fetch(url, **kwargs):
        calls.append((url, kwargs))
        return page(source, ['1'])
    board = BoardChecker(fetch)
    assert board_identity(posting(source))[0] == source
    assert [board(posting(source, i))['alive'] for i in ('1', '2')] == [True, False]
    assert len(calls) == 1
    assert 'country=' not in calls[0][0]
    if source == 'workday':
        assert json.loads(calls[0][1]['data']) == {'appliedFacets': {}, 'searchText': '', 'offset': 0, 'limit': 20}


@pytest.mark.parametrize('source', ('smartrecruiters', 'workday'))
@pytest.mark.parametrize('broken', (False, True))
def test_exhausts_pages_even_when_target_is_on_first_page(source, broken):
    calls = []
    def fetch(url, **kwargs):
        offset = json.loads(kwargs['data'])['offset'] if kwargs else int(url.rsplit('offset=', 1)[1])
        calls.append(offset)
        return page(source, ['1'] if offset == 0 else ([] if broken else ['2']), 2, offset)
    board = BoardChecker(fetch)
    assert board(posting(source))['alive'] is (None if broken else True)
    assert board(posting(source, 'missing'))['alive'] is (None if broken else False)
    assert calls == [0, 1]


@pytest.mark.parametrize('source', SOURCES)
@pytest.mark.parametrize('kind', ('error', 'invalid', 'duplicate', 'cap'))
def test_uncertain_snapshots_are_cached_unknown(source, kind, monkeypatch):
    from scraper.sources import smartrecruiters, workday
    monkeypatch.setattr(smartrecruiters, 'MAX_PAGES', 1)
    monkeypatch.setattr(workday, 'MAX_PAGES', 1)
    calls = []
    def fetch(url, **kwargs):
        calls.append(url)
        if kind == 'error':
            raise HTTPError(url, 429, 'synthetic', {}, None)
        if kind == 'invalid':
            return '{}'
        if kind == 'cap':
            return json.dumps({'jobs': [], 'hasMore': True}) if source == 'ashby' else page(source, ['1'], 2)
        return page(source, ['1', '1'])
    board = BoardChecker(fetch)
    assert board(posting(source))['alive'] is None
    assert board(posting(source, '2'))['alive'] is None
    assert len(calls) == 1


@pytest.mark.parametrize('source', SOURCES)
def test_recheck_persists_pending_own_url_gate_error_reset_and_reappearance(db, source):
    row = posting(source)
    db.execute('update postings set source=%s,external_id=%s,url=%s',
               (source, row['external_id'], row['url']))
    calls = []
    def run(ids=(), body=None, gone=False):
        Clock.current += timedelta(hours=1)
        def direct(url):
            calls.append(url)
            return {'alive': False if gone else None, 'liveness_status': 404 if gone else 200,
                    'liveness_reason': 'http-404' if gone else 'posting-url-unknown'}
        return recheck(db, scope='ats', board_checker=BoardChecker(
            lambda *a, **k: body if body is not None else page(source, ids)), checker=direct)
    assert run()['closed'] == 0 and state(db)['last_attempt_verdict'] == 'pending' and calls == []
    assert run()['closed'] == 0 and state(db)['last_attempt_verdict'] == 'unknown'
    assert calls == [row['url']] and state(db).get('alive') is not False
    assert run(body='{}')['unknown'] == 1 and state(db)['ats_miss_count'] == 0
    assert run(gone=True)['closed'] == 0 and state(db)['last_attempt_verdict'] == 'pending'
    assert run(gone=True)['closed'] == 1 and state(db)['alive'] is False
    assert run(ids=['1'])['alive'] == 1 and state(db)['alive'] is True
    assert state(db)['ats_miss_count'] == 0


def test_workday_snapshot_key_includes_cluster_and_site():
    calls = []
    board = BoardChecker(lambda url, **k: calls.append(url) or page('workday', []))
    for row in (posting('workday'), posting('workday', site='Other'), posting('workday', cluster='wd3')):
        assert board(row)['alive'] is False
    assert len(set(calls)) == 3


@pytest.mark.parametrize('source', SOURCES)
def test_stored_identity_mismatch_never_fetches(source):
    row = posting(source)
    row['url'] = row['url'].replace('/synthetic/', '/foreign/').replace('/External/', '/Other/')
    assert BoardChecker(lambda *a, **k: pytest.fail('identity mismatch'))(row)['alive'] is None


@pytest.mark.parametrize('data', (None, b'{"offset":0}'))
def test_transport_sends_honest_bounded_json_get_or_post(monkeypatch, data):
    import io
    import scraper.ats_liveness as module
    calls = []
    def open_request(request, **kwargs):
        calls.append(request)
        assert request.get_method() == ('POST' if data else 'GET')
        assert request.data == data and request.get_header('Accept') == 'application/json'
        assert 'JobRadarCoach' in request.get_header('User-agent')
        assert kwargs['timeout'] == 10
        return io.BytesIO(b'{}')
    monkeypatch.setattr(module, 'pinned_open', open_request)
    get = module.public_get()
    assert get('https://synthetic.wd5.myworkdayjobs.com/wday/cxs/synthetic/External/jobs', data=data) == '{}'
    assert len(calls) == 1
    monkeypatch.setattr(module, 'pinned_open', lambda *a, **k: io.BytesIO(b' ' * (module.BOARD_CAP + 1)))
    with pytest.raises(ValueError, match='response cap'):
        get('https://api.ashbyhq.com/oversized', data=data)
