from pathlib import Path

import psycopg
import pytest

from scraper.database import persist_postings
from test_support.postgres import migrated_database


@pytest.fixture
def db():
    with migrated_database(Path(__file__).parents[1] / 'supabase/migrations', through=19) as url, psycopg.connect(url) as connection:
        yield connection

def test_ingestion_and_rpc_preserve_structured_mode_on_rescrape(db):
    row = dict(source='test', id='mode', url='https://example.test/job',
               title='Engineer', company='Example', location='Israel (Hybrid)')
    identity = persist_postings(db, [row], '2026-10-05T03:00:00Z')[0]
    assert db.execute('select work_mode,work_mode_source,remote from postings where id=%s',
                      (identity,)).fetchone() == ('hybrid', 'location', None)
    persist_postings(db, [{**row, 'work_mode': 'remote'}], '2026-10-05T03:01:00Z')
    persist_postings(db, [row], '2026-10-05T03:02:00Z')
    assert db.execute('select work_mode,work_mode_source,remote from postings where id=%s',
                      (identity,)).fetchone() == ('remote', 'structured', True)
    assert db.execute('select work_mode from search_jobs(seen=>null)').fetchone() == ('remote',)
    assert db.execute('select work_mode from get_job(%s)', (identity,)).fetchone() == ('remote',)


def test_location_mode_changes_and_unknowns_are_not_onsite(db):
    row = dict(source='test', id='mode', url='https://example.test/job',
               title='Engineer', company='Example', location='Israel (Hybrid)')
    identity = persist_postings(db, [row], '2026-10-05T03:00:00Z')[0]
    persist_postings(db, [{**row, 'location': 'Israel (On site)'}], '2026-10-05T03:01:00Z')
    assert db.execute('select work_mode from postings where id=%s', (identity,)).fetchone() == ('on-site',)
    unknown = persist_postings(db, [{**row, 'id': 'unknown', 'location': 'Israel'}], '2026-10-05T03:02:00Z')[0]
    assert db.execute('select work_mode from postings where id=%s', (unknown,)).fetchone() == (None,)
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute("update postings set work_mode='maybe' where id=%s", (unknown,))


@pytest.mark.parametrize(('location', 'mode', 'remote'), [
    ('Remote - United States', 'remote', True),
    ('Remote (United States)', 'remote', True),
    ('Remote, Israel', 'remote', True),
    ('New York, NY; Remote - United States', None, True),
    ('Remoteville, Israel', None, None),
    ('Israel (Hybrid)', 'hybrid', None),
])
def test_remote_locations_keep_ingestion_compatibility(db, location, mode, remote):
    row = dict(source='test', id='remote-location', url='https://example.test/job',
               title='Engineer', company='Example', location=location)
    identity = persist_postings(db, [row], '2026-10-05T03:00:00Z')[0]
    assert db.execute('select work_mode,remote from postings where id=%s',
                      (identity,)).fetchone() == (mode, remote)
