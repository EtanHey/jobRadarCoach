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
    assert result['eligibility'] == 'unknown'


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


REVIEW_ATTACKS = [
    'must be authorized to work in the EU',
    'candidates located in EMEA',
    'must reside within 50 miles of our Austin office',
    'US citizenship required for clearance',
    'relocation to Singapore provided',
    'דרישה למגורים בחו״ל',
    'only applicants from LATAM',
    'on-call in CET hours',
]


@pytest.mark.parametrize('jd', REVIEW_ATTACKS + [
    'Our office is located at 5 Main Street, Boston',
    'Our Tel Aviv office is central. Our office is located at 5 Main Street, Boston',
    'Our Tel Aviv office is located between Rothschild and the Berlin hub',
    'Hybrid in our TLV or London office',
    'Hybrid in our Tel Aviv office, close to Heathrow',
    'Hybrid in our Tel Aviv office, in the Heathrow Tower',
    'Hybrid work & office environment in Atlantis',
    'Hybrid 3 days per week in Atlantis',
    'Hybrid three days per week in Atlantis',
    'Hybrid work model, must be in Atlantis',
    'Our office is in Atlantis',
    'Must work in Israel, Foobar',
    'חובה לעבוד בבלבלה',
    'ונדרש לעבוד בזיגזג',
    'על המועמדים להיות בעלי זכות חוקית לעבוד בארצות הברית',
    'Only South African citizens may apply',
    'Only Kenyan citizens may apply',
    'Remote from Israel and relocation to Singapore provided',
    'Remote from Israel and על המועמדים להיות בעלי זכות חוקית לעבוד בארצות הברית',
])
@pytest.mark.parametrize('lowercase', [False, True])
def test_review_signals_survive_cleanup_and_partial_parsing(jd, lowercase):
    jd = jd.lower() if lowercase else jd
    assert decide_location_eligibility(
        {'location': 'Tel Aviv', 'raw_jd': jd}, None, PROFILE,
    )['eligibility'] == 'unknown'


@pytest.mark.parametrize('prefix', ['', 'ב', 'מ', 'ל', 'וב', 'שב'])
def test_hebrew_outside_scope_prefixes(prefix):
    assert decide_location_eligibility(
        {'location': 'Tel Aviv', 'raw_jd': f'דרישה למגורים {prefix}חו״ל'}, None, PROFILE,
    )['eligibility'] == 'unknown'


@pytest.mark.parametrize('location', [None, '', 'Remote', 'Unknown', 'Atlantis',
                                     'London, United Kingdom', 'United States', 'Berlin, Germany',
                                     'Israel; London, United Kingdom'])
def test_workplace_extension_preserves_non_israeli_decision(location):
    jd = 'Our office is near JFK'
    expected = ({'eligibility': 'eligible', 'eligibility_reason': 'allowed location: "Israel"'}
                if location == 'Israel; London, United Kingdom' else
                {'eligibility': 'unknown', 'eligibility_reason':
                 f'Israel/remote-from-Israel scope is unconfirmed: "{location or jd}"'})
    assert decide_location_eligibility({'location': location, 'raw_jd': jd}, None, PROFILE) == expected


@pytest.mark.parametrize('jd', [
    'Hybrid model, with a gym in our building',
    'Help decide how the platform should work in the world of Vibe Coding with a background building production systems',
    'Experience working in Linux-based environments',
    'Proficiency in MS Office',
    'Squads work in SCRUM methodology',
    'Continue working in Excel as they always have',
    'Python experience with willingness to work in Java is equally welcome',
    'Map existing and candidate features into the simulation domain',
    'On-site role in Israel involves implementing backend services',
])
def test_technical_and_own_location_prose_has_no_nonown_destination(jd):
    assert decide_location_eligibility(
        {'location': 'Tel Aviv', 'raw_jd': jd}, None, PROFILE,
    )['eligibility'] == 'eligible'


@pytest.mark.parametrize('context', [
    'We have offices in London',
    'Our clients offer remote opportunities within Canada and the US',
    'Occasional business trips to Berlin',
    'Hybrid in Tel Aviv, supporting clients based in London',
    'Hybrid in Tel Aviv and work daily with teammates in London',
])
def test_context_does_not_erase_a_separate_relocation(context):
    assert decide_location_eligibility(
        {'location': 'Tel Aviv', 'raw_jd': context + ' and relocation to Singapore provided'},
        None, PROFILE,
    )['eligibility'] == 'unknown'
