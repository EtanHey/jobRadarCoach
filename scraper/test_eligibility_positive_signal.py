"""Positive Israeli fields need positive non-own signals to become unknown."""
import pytest
from scraper.eligibility import decide_location_eligibility

PROFILE = {'candidate.open_to.geographies': ['Central Israel', 'Remote']}
ATTACKS = [
    'EU-based applicants',
    'candidates in the DACH region',
    'must overlap PST hours',
    'US persons only (ITAR)',
    'תושבי חו״ל',
    'נדרשת אזרחות אמריקאית',
    'Canadian passport holders only',
    'Must work Europe/Paris hours',
    'Applicants from overseas only',
    'Our office is near JFK',
    'Hybrid from our Quasar hub',
    'Our office is close to Heathrow',
]


@pytest.mark.parametrize('jd', ATTACKS)
def test_subtle_positive_foreign_signals(jd):
    result = decide_location_eligibility({'location': 'Tel Aviv', 'raw_jd': jd}, None, PROFILE)
    assert result['eligibility'] in {'unknown', 'blocked'}


@pytest.mark.parametrize('jd', [
    'Candidates must follow company policy', 'Israeli citizenship required',
    'Must overlap IST hours', 'Must work Asia/Jerusalem hours',
    'Valid Israeli work permit mandatory', 'Hybrid infrastructure requires Python',
    'Candidates must have experience in AI/ML technologies',
    'Our Chief Architect Office provides technical guidance',
])
def test_no_positive_conflict(jd):
    assert decide_location_eligibility({'location': 'Tel Aviv', 'raw_jd': jd}, None, PROFILE)['eligibility'] == 'eligible'


@pytest.mark.parametrize('place', ['Heathrow', 'JFK', 'Quasar'])
@pytest.mark.parametrize('phrase', ['close to', 'near', 'within commuting distance of'])
def test_own_city_does_not_erase_unrecognized_proximity(place, phrase):
    jd = f'Our Tel Aviv office is {phrase} {place}'
    assert decide_location_eligibility({'location': 'Tel Aviv', 'raw_jd': jd}, None, PROFILE)['eligibility'] == 'unknown'


@pytest.mark.parametrize('jd', ['de-based applicants', 'us persons only', 'Only residents of France or Israel are eligible'])
def test_country_codes_and_inclusive_permissions(jd):
    expected = 'eligible' if jd.startswith('Only residents') else 'unknown'
    assert decide_location_eligibility({'location': 'Tel Aviv', 'raw_jd': jd}, None, PROFILE)['eligibility'] == expected
