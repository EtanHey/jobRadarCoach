"""Comeet's structured workplace type survives the existing DB projection."""
import json
from datetime import datetime, timezone

import pytest

from scraper.database import _posting_values
from scraper.sources import comeet


@pytest.mark.parametrize(('value', 'mode', 'remote'), [
    ('Remote', 'remote', True), ('Hybrid', 'hybrid', None), ('On-site', 'on-site', False),
    (None, None, None), ('Unknown', None, None), (True, None, None), ({}, None, None),
])
def test_workplace_type_maps_to_structured_mode_without_guessing(value, mode, remote):
    body = 'COMPANY_POSITIONS_DATA = ' + json.dumps([{
        'uid': 'JOB.1', 'name': 'Engineer', 'company_name': 'Synthetic',
        'url_comeet_hosted_page': 'https://www.comeet.com/jobs/synthetic/CO.1/JOB.1',
        'workplace_type': value, 'location': {'name': 'Tel Aviv'},
    }]) + '; POSITION_DATA = null;'
    row, = comeet.fetch({'slug': 'synthetic', 'company_uid': 'CO.1'},
                        fetcher=lambda _: body, before_request=lambda: None)
    assert row.get('work_mode') == mode
    values = _posting_values(row, datetime.now(timezone.utc))
    assert values[6] is remote
    assert values[-3:-1] == (mode, 'structured' if mode else None)
