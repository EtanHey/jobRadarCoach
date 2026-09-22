import json
from pathlib import Path

import pytest

from scripts.geocode_locations import Geocoder, location_query, prepare, resolved_place, single_process

PLACE = {'lat': '32.08', 'lon': '34.78', 'addresstype': 'city', 'osm_type': 'relation', 'osm_id': 1, 'display_name': 'Tel Aviv, Israel'}


def test_coordinate_precision_and_ambiguity_validation():
    assert resolved_place([PLACE])['precision'] == 'city'
    for rows in ([], [PLACE, PLACE], [PLACE | {'lat': 'NaN'}], [PLACE | {'lon': '181'}], [PLACE | {'addresstype': 'office'}], {'error': 'bad'}):
        assert resolved_place(rows) is None
    assert location_query('Tel Aviv, Israel (Hybrid)') == 'Tel Aviv, Israel'
    for location in ('Remote', 'EMEA', 'Anywhere', None, 'London / Paris', 'Israel - Office - Tel Aviv'):
        assert location_query(location) is None


def test_cache_resume_rate_limit_and_error_retry(tmp_path):
    calls, delays = [], []
    def fetch(url):
        calls.append(url)
        return [PLACE] if 'Tel' in url else []
    cache = tmp_path / 'cache.json'
    g = Geocoder(cache, fetch=fetch, one_time=True, clock=lambda: 0, sleep=delays.append)
    assert g.resolve('Tel Aviv')
    assert g.resolve('Unknown') is None
    assert len(calls) == 2 and delays == [1.1, 1.1]
    resumed = Geocoder(cache, fetch=lambda _: pytest.fail('cache hit must not fetch'))
    assert resumed.resolve('Tel Aviv') and resumed.resolve('Unknown') is None
    assert resumed.requests == 0
    slow = Geocoder(tmp_path / 'slow.json', fetch=fetch, clock=lambda: 0, sleep=delays.append)
    slow.resolve('A'); slow.resolve('B')
    assert delays[-1] == 15.1
    def fail(_):
        raise OSError('provider error')
    g.fetch = fail
    with pytest.raises(OSError):
        g.resolve('Error')
    assert len(json.loads(cache.read_text())) == 2


def test_prepare_keeps_hq_separate_and_unresolved_absent(tmp_path):
    g = Geocoder(tmp_path / 'cache.json', fetch=lambda _: [PLACE], sleep=lambda _: None)
    postings = [{'id': 'one', 'location': 'Remote', 'company': 'Acme', 'remote': True},
                {'id': 'two', 'location': 'Tel Aviv', 'company': 'Else', 'remote': False},
                {'id': 'three', 'location': None, 'company': 'Unknown', 'remote': None}]
    evidence = [{'company': 'Acme', 'city': 'Tel Aviv', 'country': 'Israel', 'source': 'https://example.test/hq', 'quote': 'HQ in Tel Aviv', 'verified_at': '2026-09-22'}]
    plan = prepare(postings, g, evidence)
    assert plan['counts'] == {'total': 3, 'mapped': 2, 'unresolved': 1}
    assert [p['posting_id'] for p in plan['posting_geo']] == ['two']
    assert plan['company_hq'][0]['source'].startswith('https://example.test/hq')
    with pytest.raises(ValueError):
        prepare(postings, g, [evidence[0] | {'source': ''}])


def test_one_process_lock(monkeypatch, tmp_path):
    monkeypatch.setattr('scripts.geocode_locations.LOCK', tmp_path / 'lock')
    with single_process():
        with pytest.raises(RuntimeError, match='Another geocoding process'):
            with single_process():
                pytest.fail('concurrent geocoder acquired lock')


@pytest.mark.parametrize('location', [
    'Canada and the US', 'US and Canada', 'United States and Canada',
    'Canada, United States', 'Ireland, Israel', '34 HaMasger Street in Tel Aviv',
    'the UK, Ireland, Estonia, the Netherlands, Sweden and Israel',
    'Global', 'customer locations', 'Remote (US East Coast timezone)',
    'US based candidates only', 'California-based', 'US-based',
    'anywhere within the United States', 'continental United States',
    'Location CountryUnited States Location StateNew Jersey Location CitySouth Plainfield',
    'Boston area', 'TLV area', 'Midtown Tel Aviv', 'Airportcity', 'Kfar Saba, IL',
])
def test_ambiguous_hosted_locations_never_use_even_a_unique_provider_match(tmp_path, location):
    g = Geocoder(tmp_path / 'cache.json', fetch=lambda _: pytest.fail('Ambiguous location must not reach provider'), sleep=lambda _: None)
    result = prepare([{'id': 'one', 'location': location, 'company': 'Example', 'remote': True}], g)
    assert result['posting_geo'] == []
    assert result['counts']['unresolved'] == 1


def test_named_places_remain_eligible():
    for location in ('Haifa, Israel', 'New Jersey', 'San Francisco Bay Area', 'SF Bay Area', 'Rehovot,ISR', 'תל אביב', 'United States, United States, US'):
        assert location_query(location) == location


def test_administrative_regional_council_is_not_labeled_as_city():
    row = PLACE | {'category': 'boundary', 'type': 'administrative', 'name': 'Misgav Regional Council'}
    assert resolved_place([row])['precision'] == 'region'


def test_review_exclusion_survives_unique_cached_match(tmp_path):
    cache = Geocoder(tmp_path / 'cache.json', fetch=lambda _: [PLACE], sleep=lambda _: None)
    assert cache.resolve('Yokneam, Israel')
    cache.fetch = lambda _: pytest.fail('Must not query provider during cached reviewed resume')
    postings = [{'id': 'one', 'location': 'Yokneam, Israel', 'company': 'Example', 'remote': False}]
    plan = prepare(postings, cache, excluded_queries=['Yokneam, Israel'])
    assert plan['posting_geo'] == [] and plan['counts']['unresolved'] == 1
    assert plan['unresolved'][0]['reason'] == 'reviewed_ambiguous'
    with pytest.raises(ValueError):
        prepare(postings, cache, excluded_queries='Yokneam, Israel')


@pytest.mark.parametrize('location', ['anywhere in the world', 'work from anywhere in the world'])
def test_global_prose_from_refreshed_snapshot_never_queries_provider(tmp_path, location):
    g = Geocoder(tmp_path / 'cache.json', fetch=lambda _: pytest.fail('Global prose is not a named place'), sleep=lambda _: None)
    plan = prepare([{'id': 'one', 'location': location, 'company': 'Example', 'remote': True}], g)
    assert plan['counts'] == {'total': 1, 'mapped': 0, 'unresolved': 1}
