import pytest

from scraper.annotate import location_mode, posting_mode


@pytest.mark.parametrize(('location', 'mode'), [
    ('Yavne, Israel (Hybrid)', 'hybrid'), ('Tel Aviv-Yafo (hYbRiD)', 'hybrid'),
    ('Tel Aviv · Remote', 'remote'), ('Israel - On-site', 'on-site'),
    ('Israel (Onsite)', 'on-site'), ('Israel (On site)', 'on-site'),
    ('Remote', 'remote'), ('Israel [Hybrid]', 'hybrid'),
    ('Remoteville', None), ('Hybrid City', None), ('Remote - Israel', 'remote'),
    ('Israel (not remote)', None), ('Israel (Hybrid / Remote)', None),
    ('Israel (Remote) (On-site)', None), ('Israel', None), (None, None),
])
def test_only_unambiguous_location_labels(location, mode):
    assert location_mode(location) == mode


@pytest.mark.parametrize(('posting', 'expected'), [
    ({'location': 'Israel (Hybrid)'}, ('hybrid', 'location')),
    ({'location': 'Israel (Hybrid)', 'remote': True}, ('remote', 'structured')),
    ({'location': 'Israel (Remote)', 'remote': False}, ('on-site', 'structured')),
    ({'location': 'Israel (Remote)', 'work_mode': 'hybrid'}, ('hybrid', 'structured')),
    ({'location': 'Israel', 'work_mode': 'onsite'}, ('on-site', 'structured')),
    ({'location': 'Israel', 'work_mode': 'unknown'}, (None, None)),
])
def test_structured_values_take_precedence(posting, expected):
    assert posting_mode(posting) == expected

@pytest.mark.parametrize(('location', 'mode'), [
    ('Israel Hybrid', 'hybrid'), ('Israel ( Fully Remote )', 'remote'),
    ('Israel (Remote', None), ('Israel Remote)', None),
    ('Israel [Hybrid)', None), ('Israel (On site) campus', None),
])
def test_common_trailing_labels_require_balanced_brackets(location, mode):
    assert location_mode(location) == mode


@pytest.mark.parametrize(('location', 'mode'), [
    ('Remote - United States', 'remote'), ('Remote (United States)', 'remote'),
    ('Remote, Israel', 'remote'), ('rEmOtE – Canada', 'remote'),
    ('Fully Remote (United States)', 'remote'),
    ('Remoteville - United States', None), ('Remote Sensing - United States', None),
    ('Remote (United States', None), ('Remote - Hybrid', None),
    ('Remote (United States) (On-site)', None),
])
def test_leading_remote_locations_and_neighbours(location, mode):
    assert location_mode(location) == mode
