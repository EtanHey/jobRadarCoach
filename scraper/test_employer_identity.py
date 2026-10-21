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
