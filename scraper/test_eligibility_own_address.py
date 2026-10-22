"""Own-office addresses resolve without erasing independent workplace limits."""
import pytest

from scraper.eligibility import decide_location_eligibility
from scraper.geography import _city_matches_country, normalize_israeli_location

PROFILE = {'candidate.open_to.geographies': ['Central Israel', 'Remote']}


@pytest.mark.parametrize('location,jd', [
    ('Tel Aviv-Yafo, Tel Aviv District, Israel', 'Join us in our Tel Aviv office three days a week'),
    ('Tel Aviv', 'Hybrid model: Join us in our Tel Aviv office three days a week (Tue–Thu)'),
    ('Tel Aviv', 'Our office is located in Tel Aviv, between Rothschild Boulevard and Neve Tzedek'),
    ('Tel Aviv', 'Hybrid work with our new offices located at 34 HaMasger Street in Tel Aviv'),
    ('34 HaMasger Street in Tel Aviv', 'Hybrid work with our new offices located at 34 HaMasger Street in Tel Aviv'),
    ('Tel Aviv', 'Our office is situated in the heart of TLV, in Midtown, close to the light rail and train station'),
    ('Ramat Gan', 'Our Israel office is located in the Bursa area of Ramat Gan.This role is on-site'),
    ('Tel Aviv', 'This role is based fully on-site from the Attribute Tel Aviv office, located in Carlibach St 29 Tel Aviv, center'),
    ('Carlibach St 29 Tel Aviv, Israel', 'This role is based fully on-site from the Attribute Tel Aviv office, located in Carlibach St 29 Tel Aviv, Israel.'),
    ('Tel Aviv', 'Our office is located in Tel Aviv, at Carlibach St. 29'),
    ('Tel Aviv', 'Our office is located in Tel Aviv, at 29 Carlibach Rd'),
    ('Tel Aviv', 'Our office is located in Tel Aviv, at 29 Carlibach Ave'),
    ('Tel Aviv', 'Our office is located in Tel Aviv, at 29 Carlibach Blvd'),
    ('Tel Aviv', 'Our office is located in Tel Aviv, at רחוב קרליבך 29'),
    ('Tel Aviv', 'Our office is located in Tel Aviv, at רח׳ קרליבך 29'),
    ('Tel Aviv', 'Our office is located in Tel Aviv, at שדרות רוטשילד 29'),
    ('Tel Aviv', 'Our office is located in Tel Aviv, in the Azrieli Tower'),
    ('Tel Aviv', 'Our office is located in Tel Aviv, close to Sarona Market'),
    ('Tel Aviv', 'Ready to work in an office environment most days of the week'),
    ('Tel Aviv', 'Work in the office most days a week'),
    ('Tel Aviv', 'Hybrid in our Israeli office'),
    ('Tel-Aviv-Yafo, Israel', 'Hybrid in our TLV office'),
    ('Ramat-Gan, Israel', 'Hybrid in our Ramat Gan office'),
    ('Herzliya, Israel', 'Hybrid in our Herzeliya office'),
    ('Petah Tikva', 'Hybrid in our Petach Tikva office'),
    ('Kfar Saba', 'Hybrid in our Kefar Sava office'),
])
def test_own_city_and_address(location, jd):
    assert decide_location_eligibility({'location': location, 'raw_jd': jd}, None, PROFILE)['eligibility'] == 'eligible'


@pytest.mark.parametrize('jd', [
    'Hybrid in our Ramat Gan office',
    'Our Israel office is located in the Bursa area of Ramat Gan',
    'Hybrid with offices in New York and Tel Aviv',
    'Hybrid with offices in Tel Aviv and New York',
    'Our Tel Aviv office is located between London and Berlin',
    'Our Tel Aviv office is close to Berlin',
    'Our Tel Aviv office is in the London Tower',
    'Our Tel Aviv office is located at 29 New York Street',
    'Hybrid in our Warsaw office, located at 29 Carlibach Street in Tel Aviv',
    'Hybrid in the London Tel Aviv office, located in Carlibach St 29 Tel Aviv',
    'Hybrid in the Attribute Tel Aviv office, located in Carlibach St 29 Ramat Gan',
    'Hybrid in our office in Tel Aviv, at 29 Carlibach Street, and must reside in Warsaw',
    'Hybrid in our office in Tel Aviv, at 29 Carlibach Street, US citizenship required',
    'Hybrid in our office in Tel Aviv, at 29 Carlibach Street, and weekly attendance at our dublin workspace',
    'Hybrid in our office in Tel Aviv, close to Sarona Market and must hold EU citizenship',
    'Hybrid in our office in Tel Aviv, between Rothschild Boulevard and Neve Tzedek and must live in Berlin',
    'Hybrid in our office in Tel Aviv, at רחוב קרליבך 29 וחובה לגור בלונדון',
    'Our Tel Aviv office is in Atlantis',
])
def test_address_does_not_hide_other_places_or_obligations(jd):
    assert decide_location_eligibility({'location': 'Tel Aviv', 'raw_jd': jd}, None, PROFILE)['eligibility'] == 'unknown'


@pytest.mark.parametrize('alias,canonical', [
    ('TLV', 'Tel Aviv'), ('Tel-Aviv-Yafo', 'Tel Aviv'),
    ('Ramat-Gan', 'Ramat Gan'), ('Herzeliya', 'Herzliya'),
    ('Kefar Sava', 'Kfar Saba'), ('Petach Tikva', 'Petah Tikva'),
])
def test_aliases_are_shared_with_ingestion(alias, canonical):
    assert normalize_israeli_location(alias) == canonical
    assert _city_matches_country(alias, 'israel')
    assert not _city_matches_country(f'{alias}, Germany', 'israel')


def test_sarid_commute_scope_remains_unconfirmed():
    row = {'location': 'Sarid, Israel (Hybrid)', 'company': 'Tomax Think Academy',
           'raw_jd': '> Tomax Think Academy · Sarid, Israel (Hybrid) · Part-time · Posted 2026-09-15'}
    assert decide_location_eligibility(row, None, PROFILE)['eligibility'] == 'unknown'
