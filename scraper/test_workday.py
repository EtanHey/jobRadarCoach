"""Synthetic Workday contracts: active-list truth, publication and common gates."""
import json
from datetime import date
from email.message import Message

import pytest
from scraper import cloud_run, harvest, source_registry, liveness, recheck, description_backfill
from scraper.sources import workday as adapter
from scraper.test_liveness import Response

QUERY = {'account': 'synthetic', 'cluster': 'wd5', 'site': 'External', 'company': 'Synthetic Labs'}
BASE = 'https://synthetic.wd5.myworkdayjobs.com'
API = BASE + '/wday/cxs/synthetic/External'
PATH = '/job/Israel-Tel-Aviv/Frontend-Engineer_R123'
URL = BASE + '/External' + PATH
FACETS = [{'facetParameter': 'locationMainGroup', 'values': [
    {'facetParameter': 'locationHierarchy1', 'values': [{'descriptor': 'Israel', 'id': 'synthetic-country'}]}]}]


def job(**changes):
    return {'title': 'Frontend Engineer', 'externalPath': PATH, 'locationsText': '2 Locations',
            'postedOn': 'Posted 30+ Days Ago', 'bulletFields': ['R123'], **changes}


def page(records, total=None):
    return {'total': len(records) if total is None else total, 'jobPostings': records, 'facets': FACETS}


def detail(**changes):
    return {'jobPostingInfo': {'jobReqId': 'R123', 'jobPostingSiteId': 'External', 'title': 'Frontend Engineer',
        'externalUrl': URL, 'location': 'United States, Remote', 'additionalLocations': ['Israel, Tel Aviv'],
        'startDate': '2026-09-30', 'postedOn': 'Posted 30+ Days Ago', 'posted': False,
        'jobDescription': '<p>Build synthetic frontend software. </p>' * 8 + '<p>4 years experience.</p>', **changes}}


def fetch(records=None, detail_changes=None, **kwargs):
    calls = []
    def loader(url, **options):
        calls.append((url, options))
        return json.dumps(page(records or [job()]) if url.endswith('/jobs') else detail(**(detail_changes or {})))
    return adapter.fetch(QUERY, fetcher=loader, before_request=lambda: None, **kwargs), calls


def test_maps_secondary_israel_active_list_and_actual_absolute_date():
    rows, calls = fetch()
    row = rows[0]
    assert row['source'] == 'workday' and row['url'] == URL and row['id'].startswith('workday:synthetic:External:')
    assert row['alive'] is True and row['liveness_reason'] == 'workday-active-list'
    assert row['posted_at'] == '2026-09-30' and row['posted_ago'] == 'Posted 30+ Days Ago'
    assert 'Israel, Tel Aviv' in row['location'] and '4 years experience.' in row['jd_text'] and row['jd_fetched']
    assert calls[0][0] == API + '/jobs' and json.loads(calls[0][1]['data'])['limit'] == 20
    assert json.loads(calls[1][1]['data'])['appliedFacets'] == {'locationHierarchy1': ['synthetic-country']}


@pytest.mark.parametrize('value', [None, '', 'invalid', 'Posted Today', '2026-09-31'])
def test_relative_or_missing_dates_are_never_clock_anchored(value):
    assert fetch(detail_changes={'startDate': value})[0][0]['posted_at'] == ''


def test_prefilter_excluded_titles_never_fetches_details():
    rows, calls = fetch(records=[job(title='QA Engineer')], posting_filter=lambda _: False)
    assert rows == [] and len(calls) == 2


@pytest.mark.parametrize('payload', [{}, [], page([], 1), page([job(externalPath='https://evil.invalid/job')]),
    page([job(title=None)]), page([job(bulletFields=[])]), page([job()], False)])
def test_malformed_or_partial_list_is_failure(payload):
    with pytest.raises(ValueError):
        list(adapter.active_list(QUERY, fetcher=lambda *a, **k: json.dumps(payload)))


@pytest.mark.parametrize('second_total', [0, 2])
def test_id_scoped_pagination_liveness_never_uses_single_job_details(second_total):
    calls = []
    def loader(url, **options):
        body = json.loads(options['data'])
        calls.append((url, body))
        return json.dumps(page([job(externalPath='/job/Israel/Other_R999')], 2) if body['offset'] == 0
                          else page([job()], second_total))
    assert adapter.is_active(QUERY, PATH, fetcher=loader) is True
    assert calls[-1][1]['offset'] == 1 and calls[-1][1]['searchText'] == 'R123'
    assert adapter.is_active(QUERY, PATH, fetcher=lambda *a, **k: json.dumps(page([]))) is False
    assert adapter.is_active(QUERY, PATH, fetcher=lambda *a, **k: json.dumps(page([], 1))) is None
    assert all(url == API + '/jobs' for url, _ in calls)


def test_active_truth_registry_allowlist_and_budgets(tmp_path, monkeypatch):
    rows, _ = fetch()
    assert harvest.apply_liveness_checks(rows, lambda _: pytest.fail('retain active-list truth'))[0]['alive'] is True
    tenant = {'source': 'workday', 'identifiers': {k: QUERY[k] for k in ('account', 'cluster', 'site')},
        'company': 'Synthetic Labs', 'careers_url': BASE + '/External', 'enabled': True,
        'last_verified_at': '2026-10-04', 'provenance': [{'kind': 'synthetic', 'reference': 'https://example.invalid'}]}
    path = tmp_path / 'registry.json'
    path.write_text(json.dumps({'schema_version': 1, 'tenants': [tenant]}))
    assert source_registry.load_registry(path, as_of=date(2026, 10, 4)).source_queries()['workday'][0]['site'] == 'External'
    assert source_registry.detect_supported_ats(URL)['identifiers'] == tenant['identifiers']
    assert source_registry.public_endpoint(tenant) == API + '/jobs'
    monkeypatch.setattr(cloud_run, 'REGISTRY_PATH', path)
    assert cloud_run._registry_request_limits()['workday'] >= 26
    for bad in ['https://synthetic.wd5.myworkdayjobs.com.evil.invalid/External', BASE + ':444/External',
                'https://evil@synthetic.wd5.myworkdayjobs.com/External']:
        assert source_registry.detect_supported_ats(bad) is None


def test_recheck_and_jd_retry_use_honest_public_api():
    calls = []
    def opener(request, **kwargs):
        calls.append(request)
        assert request.get_header('User-agent') == harvest.USER_AGENT
        response = Response(200, request.full_url, json.dumps(page([job()]) if request.data else detail()))
        response.headers = Message()
        return response
    assert liveness.check_url(URL, opener=opener)['alive'] is True
    assert json.loads(calls[0].data)['searchText'] == 'R123' and calls[0].full_url == API + '/jobs'
    assert '4 years experience.' in description_backfill._fetch(URL, opener=opener)
    assert calls[-1].full_url == API + PATH and recheck.public_job_url(URL)
    assert "'workday'" in recheck.SELECT_STALE and "'workday'" in description_backfill.SELECT


def test_pipeline_keeps_shared_title_location_and_year_rules(tmp_path, monkeypatch):
    monkeypatch.setattr(harvest, 'load_searches', lambda _: [{'keywords': 'Frontend Engineer', 'location': 'Israel', 'recency': 'r604800'}])
    monkeypatch.setattr(harvest, 'load_profile_contract', lambda _: {'fit_terms': {'frontend'}})
    monkeypatch.setattr(harvest, 'load_source_queries', lambda *a, **k: {})
    monkeypatch.setattr(harvest, 'load_registry_source_queries', lambda: {'workday': [QUERY]})
    monkeypatch.setattr(harvest, 'harvest_search', lambda *a, **k: ([], 0))
    records = [job(), job(title='QA Engineer', externalPath='/job/Israel/QA_R222'),
        job(title='Senior Frontend Engineer', externalPath='/job/Israel/Senior_R333', bulletFields=['R333']),
        job(externalPath='/job/US/Frontend_R444', bulletFields=['R444'])]
    calls = []
    def loader(url, **options):
        calls.append(url)
        if url.endswith('/jobs'):
            return json.dumps(page(records))
        info = detail()
        if 'R333' in url:
            info = detail(jobReqId='R333', externalUrl=BASE + '/External/job/Israel/Senior_R333',
                jobDescription='Minimum 7 years of experience required. ' * 8)
        if 'R444' in url:
            info = detail(jobReqId='R444', externalUrl=BASE + '/External/job/US/Frontend_R444', additionalLocations=[])
        return json.dumps(info)
    result = harvest.run_pipeline(config_path=tmp_path/'config', profile_path=tmp_path/'profile', output_dir=tmp_path/'out',
        date_string='2026-10-04', harvested_at='2026-10-04T12:00:00Z', max_pages=1,
        fetcher=loader, before_request=lambda: None, enabled_sources={'workday'},
        liveness_checker=lambda _: pytest.fail('active list'))
    assert result['source_fetch_counts']['workday'] == 4 and result['source_match_counts']['workday'] == 2
    assert result['source_counts']['workday'] == 1 and result['new_published_count'] == 1 and len(calls) == 5


def test_json_post_survives_cloud_pacing_and_separate_detail_budget(tmp_path, monkeypatch):
    monkeypatch.setenv('DATABASE_URL', 'postgresql://example.invalid/synthetic')
    calls = []
    monkeypatch.setattr(harvest, 'fetch_html', lambda url, **kw: calls.append((url, kw)) or 'body')
    monkeypatch.setattr(harvest, 'RequestPacer', lambda: lambda: None)
    def run(_):
        for _ in range(10):
            harvest.fetch_html(API + PATH)
        harvest.fetch_html(API + '/jobs', data=b'{"limit":20}')
        print('{}')
        return 0
    assert cloud_run.main(['--receipt', str(tmp_path/'receipt')], harvest_main=run) == 0
    assert len(calls) == 9 and calls[-1][1]['data'] == b'{"limit":20}'


@pytest.mark.parametrize('data', [None, b'{"limit":20}'])
def test_real_transport_sends_json_requests_with_honest_headers(data):
    def opener(request, **kwargs):
        assert request.get_method() == ('POST' if data else 'GET') and request.data == data
        assert request.get_header('Accept') == 'application/json'
        assert request.get_header('User-agent') == harvest.USER_AGENT
        response = Response(200, request.full_url, '{}')
        response.read = lambda *args: b'{}'
        return response
    assert harvest.fetch_html(API + '/jobs', data=data, opener=opener, backoffs=()) == '{}'
