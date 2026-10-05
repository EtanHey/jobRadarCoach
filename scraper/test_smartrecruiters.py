"""Synthetic public SmartRecruiters contracts; no owner profile fixtures."""
import importlib
import json
from datetime import date

import pytest
from scraper import cloud_run, harvest, source_registry

ACCOUNT = 'SyntheticLabs'
JOB_ID = '12345678'
QUERY = {'account': ACCOUNT, 'company': 'Synthetic Labs'}
API = f'https://api.smartrecruiters.com/v1/companies/{ACCOUNT}/postings'
URL = f'https://jobs.smartrecruiters.com/{ACCOUNT}/{JOB_ID}-frontend-engineer'


def job(**changes):
    return {'id': JOB_ID, 'name': 'Frontend Engineer', 'company': {'identifier': ACCOUNT},
            'location': {'city': 'Tel Aviv', 'country': 'il', 'remote': False},
            'releasedDate': '2026-09-30T12:00:00Z', **changes}


def page(records, *, offset=0, total=None):
    return {'content': records, 'offset': offset, 'limit': 100,
            'totalFound': len(records) if total is None else total}


def detail(**changes):
    return {**job(), 'postingUrl': URL, 'active': False,
            'jobAd': {'sections': {'jobDescription': {'text': '<p>Build synthetic frontend software. </p>' * 8},
                                   'qualifications': {'text': '<p>4 years experience.</p>'}}}, **changes}


def fetch(records=None, payload=None, **kwargs):
    adapter = importlib.import_module('scraper.sources.smartrecruiters')
    calls = []
    def loader(url):
        calls.append(url)
        return json.dumps(payload if payload is not None else page(records or [job()])) if '?' in url else json.dumps(detail())
    rows = adapter.fetch(QUERY, fetcher=loader, before_request=lambda: None, **kwargs)
    return rows, calls


def test_maps_active_list_truth_and_complete_jd_with_provider_date():
    rows, calls = fetch()
    row = rows[0]
    assert row['id'] == f'smartrecruiters:{ACCOUNT}:{JOB_ID}'
    assert row['source'] == 'smartrecruiters' and row['url'] == URL
    assert row['alive'] is True and row['liveness_reason'] == 'smartrecruiters-active-list'
    assert row['posted_at'] == '2026-09-30T12:00:00Z'
    assert 'Israel' in row['location'] and row['remote'] is False
    assert '4 years experience.' in row['jd_text'] and row['jd_fetched'] is True
    assert calls == [API + '?limit=100&offset=0&country=il', API + '/' + JOB_ID]


@pytest.mark.parametrize('timestamp', [None, '', 'invalid', '2026-09-30', '2026-09-30T12:00:00'])
def test_missing_or_ambiguous_publication_dates_are_not_invented(timestamp):
    assert fetch(records=[job(releasedDate=timestamp)])[0][0]['posted_at'] == ''


def test_prefilter_avoids_detail_requests_for_excluded_roles():
    rows, calls = fetch(records=[job(name='QA Engineer')], posting_filter=lambda _: False)
    assert rows == [] and len(calls) == 1


@pytest.mark.parametrize('payload', [[], {}, {'content': []}, page([], total=1), page([job(id='')]),
    page([job(company={'identifier': 'OtherCompany'})]), page([job()], offset=100), page([job(name=None)]),
    {**page([job()]), 'offset': False}, {**page([job()]), 'limit': 0}])
def test_malformed_or_partial_lists_are_failures_not_empty_boards(payload):
    with pytest.raises((ValueError, RuntimeError)):
        fetch(payload=payload)


def test_paginated_membership_and_absence_require_active_list_completion():
    adapter = importlib.import_module('scraper.sources.smartrecruiters')
    calls = []
    def loader(url):
        calls.append(url)
        return json.dumps(page([job(id='111')], total=2) if 'offset=0' in url else page([job()], offset=1, total=2))
    assert adapter.is_active(ACCOUNT, JOB_ID, fetcher=loader) is True
    assert adapter.is_active(ACCOUNT, '999', fetcher=loader) is False
    assert all('/postings?' in url for url in calls)
    assert adapter.is_active(ACCOUNT, '999', fetcher=lambda _: json.dumps(page([job()], total=2))) is None


def test_active_list_truth_survives_generic_page_liveness_checks():
    rows, _ = fetch()
    assert harvest.apply_liveness_checks(rows, lambda _: pytest.fail('must retain board truth'))[0]['alive'] is True


def test_source_registry_budget_and_public_endpoint(tmp_path, monkeypatch):
    tenant = {'source': 'smartrecruiters', 'identifiers': {'account': ACCOUNT}, 'company': 'Synthetic Labs',
              'careers_url': f'https://careers.smartrecruiters.com/{ACCOUNT}', 'enabled': True,
              'last_verified_at': '2026-10-04', 'provenance': [{'kind': 'synthetic', 'reference': 'https://example.invalid'}]}
    path = tmp_path / 'registry.json'
    path.write_text(json.dumps({'schema_version': 1, 'tenants': [tenant]}))
    report = source_registry.load_registry(path, as_of=date(2026, 10, 4))
    assert report.source_queries()['smartrecruiters'][0]['account'] == ACCOUNT
    monkeypatch.setattr(cloud_run, 'REGISTRY_PATH', path)
    assert cloud_run._registry_request_limits()['smartrecruiters'] >= 2
    detected = source_registry.detect_supported_ats(URL)
    assert detected['identifiers'] == {'account': ACCOUNT}
    assert source_registry.public_endpoint(detected) == API + '?limit=100&offset=0&country=il'


@pytest.mark.parametrize(('payload', 'alive'), [(page([job()]), True), (page([]), False),
    (page([job(id='999')]), False), (page([], total=1), None), ({'content': 'bad'}, None)])
def test_stored_recheck_never_uses_single_posting_details(payload, alive):
    from scraper import liveness, recheck
    from scraper.test_liveness import Response
    calls = []
    def opener(request, **kwargs):
        calls.append(request.full_url)
        assert request.get_header('User-agent') == harvest.USER_AGENT
        return Response(200, request.full_url, json.dumps(payload))
    assert liveness.check_url(URL, opener=opener)['alive'] is alive
    assert calls == [API + '?limit=100&offset=0']
    assert recheck.public_job_url(URL) and "smartrecruiters" in recheck.ATS_SOURCES


def test_description_retry_uses_details_for_text_only():
    from email.message import Message
    from scraper import description_backfill
    from scraper.test_liveness import Response
    calls = []
    def opener(request, **kwargs):
        calls.append(request.full_url)
        assert request.get_header('User-agent') == harvest.USER_AGENT
        result = Response(200, request.full_url, json.dumps(detail()))
        result.headers = Message()
        return result
    assert '4 years experience.' in description_backfill._fetch(URL, opener=opener)
    assert calls == [API + '/' + JOB_ID]
    assert "'smartrecruiters'" in description_backfill.SELECT


def test_pipeline_keeps_shared_country_title_and_year_rules(tmp_path, monkeypatch):
    searches = [{'keywords': 'Frontend Engineer', 'location': 'Israel', 'recency': 'r604800'}]
    monkeypatch.setattr(harvest, 'load_searches', lambda _: searches)
    monkeypatch.setattr(harvest, 'load_profile_contract', lambda _: {'fit_terms': {'frontend'}})
    monkeypatch.setattr(harvest, 'load_source_queries', lambda *args, **kwargs: {})
    monkeypatch.setattr(harvest, 'load_registry_source_queries', lambda: {'smartrecruiters': [QUERY]})
    monkeypatch.setattr(harvest, 'harvest_search', lambda *args, **kwargs: ([], 0))
    records = [job(), job(id='222', name='Senior Frontend Engineer'), job(id='333', name='QA Engineer'),
               job(id='444', location={'city': 'Berlin', 'country': 'de'})]
    calls = []
    def loader(url):
        calls.append(url)
        if '?' in url:
            return json.dumps(page(records))
        job_id = url.rsplit('/', 1)[-1]
        payload = detail(id=job_id)
        if job_id == '222':
            payload['jobAd']['sections']['qualifications']['text'] = 'Minimum 7 years of experience required.'
        return json.dumps(payload)
    result = harvest.run_pipeline(config_path=tmp_path / 'searches.json', profile_path=tmp_path / 'profile.yaml',
        output_dir=tmp_path / 'output', date_string='2026-10-04', harvested_at='2026-10-04T12:00:00Z',
        max_pages=1, fetcher=loader, before_request=lambda: None, enabled_sources={'smartrecruiters'},
        liveness_checker=lambda _: pytest.fail('active-list truth required'))
    assert result['source_fetch_counts']['smartrecruiters'] == 4
    assert result['source_match_counts']['smartrecruiters'] == 2
    assert result['source_counts']['smartrecruiters'] == 1 and result['new_published_count'] == 1
    assert len(calls) == 3  # Board plus two admitted details; no excluded-role requests.


def test_detail_budget_does_not_starve_board_fetches(tmp_path, monkeypatch):
    monkeypatch.setenv('DATABASE_URL', 'postgresql://example.invalid/synthetic')
    calls = []
    monkeypatch.setattr(harvest, 'fetch_html', lambda url, **kwargs: calls.append(url) or 'body')
    monkeypatch.setattr(harvest, 'RequestPacer', lambda: lambda: None)
    def run(_):
        for number in range(10):
            harvest.fetch_html(API + '/' + str(number))
        harvest.fetch_html(API + '?limit=100&offset=0&country=il')
        print('{}')
        return 0
    assert cloud_run.main(['--receipt', str(tmp_path / 'receipt.json')], harvest_main=run) == 0
    assert len(calls) == 9 and calls[-1].endswith('&country=il')
