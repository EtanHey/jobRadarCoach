"""Frozen triage shapes; no private scoring or candidate data."""
import json
from pathlib import Path

import pytest

from scraper.employer_identity import resolve_employer

ROWS = json.loads((Path(__file__).parents[1] / 'test_support/fixtures/employer_identity.json').read_text())


@pytest.mark.parametrize('row', ROWS, ids=lambda row: row['company'])
def test_snapshot_identity(row):
    result = resolve_employer(row['company'], row['raw_jd'], row['source'])
    expected = {'EngRadar': 'Monday.com', 'Torentify': None, 'Wix': 'Wix'}
    assert result['publisher'] == row['company']
    assert result['hiring_employer'] == expected[row['company']]
    if result['hiring_employer']:
        assert result['employer_evidence'] in row['raw_jd'] or result['employer_evidence'].startswith('source:')


@pytest.mark.parametrize('jd, expected', [
    ('Recruiting on behalf of Acme Labs for an engineer.', 'Acme Labs'),
    ('Our client Acme Labs is hiring an engineer.', 'Acme Labs'),
    ('Acme Labs is hiring an engineer.', 'Acme Labs'),
    ('Our client is a leading fintech company.', None),
    ('**About The Company**\n\nOur mission at Ōura is to empower people.', None),
    ('This employer is hiring engineers.', None),
    ('Acme Labs is hiring engineers.\nBeta Labs is hiring engineers.', None),
    ('Experience with React and Monday.com is required.', None),
    ('We are hiring engineers. Acme Labs is hiring engineers.', None),
])
def test_explicit_names_only(jd, expected):
    assert resolve_employer('Torentify', jd, 'linkedin')['hiring_employer'] == expected


def test_absent_agency_evidence_is_not_direct():
    assert resolve_employer('New Publisher', 'Build React apps.', 'linkedin')['hiring_employer'] is None


def test_publisher_catalog_matches_browser_catalog():
    from scraper.employer_publishers import PUBLISHERS
    assert list(PUBLISHERS) == json.loads((Path(__file__).parents[1] / 'ui/lib/employer-publishers.json').read_text())


@pytest.mark.parametrize('publisher,jd', [
    ('AgileGrid Solutions', '**About The Company**\n\nQuik Hire Staffing is a leading provider of innovative staffing solutions connecting professionals with client organizations.\n\n**About The Role**\n\nWe are seeking a Frontend Developer for a global software company.'),
    ('מרטנס | Mertens – מקבוצת מלם תים', 'Mertens - MalamTeam is hiring a Backend Developer to join a leading organization in the Gush Dan area'),
    ('New Publisher', '**About The Company**\n\nTalent Bridge is a recruiting firm placing engineers with clients.\n\n**About The Role**\n\nWe seek an engineer for an unnamed client.'),
    ('New Publisher', 'Talent Bridge is hiring a developer to join a leading organization.'),
])
def test_intermediary_is_not_hiring_employer(publisher, jd):
    result = resolve_employer(publisher, jd, 'linkedin')
    assert result['hiring_employer'] is None
    assert result['agency_evidence'] in jd


@pytest.mark.parametrize('role,expected', [
    ('Scribe in San Francisco is seeking a Senior Frontend Engineer.', 'Scribe'),
    ('Scribe is seeking a Senior Frontend Engineer.', 'Scribe'),
    ('Scribe is seeking an engineer.\nBeta Labs is hiring an engineer.', None),
])
def test_role_identity_overrides_conflicting_blurb(role, expected):
    jd = '**About The Company**\n\nCantos Ventures is an investment firm.\n\n**About The Role**\n\n' + role
    result = resolve_employer('Netrolynx AI', jd, 'linkedin')
    assert result['hiring_employer'] == expected
    if expected:
        assert 'Scribe' in result['employer_evidence']
        assert 'Cantos' not in result['employer_evidence']


ALIASES = [
    ('Alice (Formerly ActiveFence)', 'Alice'),
    ('BMC Software', 'BMC'),
    ('EyeContact Dx', 'EyeContact'),
    ('IAI - Israel Aerospace Industries', 'Israel Aerospace Industries Aviation Division'),
    ('Ness Technologies | נס טכנולוגיות', 'NESS FORCE'),
    ('Ness Technologies | נס טכנולוגיות', 'Ness'),
    ('Nova Ltd.', 'Nova'),
    ('Parsons Corporation', 'Parsons'),
    ('Ripple Analytics', 'Ripple'),
    ('SWAKIO™', 'SWAKIO'),
]


@pytest.mark.parametrize('publisher,employer', ALIASES)
def test_reviewed_alias_is_not_different_employer(publisher, employer):
    result = resolve_employer(publisher, f'**About The Company**\n\n{employer} is building software.', 'linkedin')
    assert result['hiring_employer'] == employer
    assert result['relationship'] == 'alias'


def test_agency_can_name_an_actual_client():
    jd = '**About The Company**\n\nTalent Bridge is a staffing firm.\n\n**About The Role**\n\nOur client Acme Labs is hiring a developer.'
    result = resolve_employer('New Publisher', jd, 'linkedin')
    assert result['hiring_employer'] == 'Acme Labs'
    assert result['agency_evidence'] in jd


def test_role_conflict_does_not_fall_back_to_ats_publisher():
    jd = 'Acme Labs is hiring an engineer.\nBeta Labs is hiring an engineer.'
    assert resolve_employer('Example', jd, 'greenhouse')['hiring_employer'] is None


@pytest.mark.parametrize('jd', [
    'Mobileye is looking for an engineer to join our Algorithms organization.',
    'NVIDIA is seeking an engineer to join our System Product Engineering organization.',
])
def test_internal_organization_is_not_agency_evidence(jd):
    publisher = jd.split()[0]
    result = resolve_employer(publisher, jd, 'linkedin')
    assert result['hiring_employer'] == publisher
    assert result['agency_evidence'] is None


def test_unnamed_role_client_does_not_fall_back_to_company_blurb():
    jd = '**About The Company**\n\nAcme Labs is a software company.\n\n**About The Role**\n\nTalent Bridge is hiring a developer to join a leading organization.'
    assert resolve_employer('New Publisher', jd, 'linkedin')['hiring_employer'] is None


def test_reviewed_alias_catalog_matches_browser():
    from scraper.employer_aliases import ALIASES
    assert ALIASES == json.loads((Path(__file__).parents[1] / 'ui/lib/employer-aliases.json').read_text())


def test_unlisted_publisher_can_have_explicit_unnamed_client_evidence():
    jd = 'Our client is a leading fintech company seeking an engineer.'
    result = resolve_employer('New Publisher', jd, 'linkedin')
    assert result['hiring_employer'] is None
    assert result['agency_evidence'] == jd


@pytest.mark.parametrize('jd', [
    'Our client success team builds developer tools.',
    'Our client SDK supports React.',
])
def test_client_product_or_team_is_not_agency_evidence(jd):
    result = resolve_employer('New Publisher', jd, 'linkedin')
    assert result['hiring_employer'] is None
    assert result['agency_evidence'] is None


def test_staffing_software_is_not_a_staffing_intermediary():
    jd = '**About The Company**\n\nAcme Labs is a staffing software platform.'
    result = resolve_employer('Acme Labs', jd, 'linkedin')
    assert result['hiring_employer'] == 'Acme Labs'
    assert result['agency_evidence'] is None
