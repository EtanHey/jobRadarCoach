import json
from pathlib import Path

import psycopg
import pytest
from psycopg.rows import dict_row

from scripts.globe_geocode import apply_plan, rollback_plan
from scripts.geocode_locations import hq_eligible
from test_support.postgres import migrated_database
from test_support.test_job_api import _seed, IDS


def test_apply_resume_rollback_preserves_existing_and_later_operator_edits(tmp_path):
    with migrated_database(Path(__file__).parents[1] / 'supabase/migrations', through=17) as url:
        with psycopg.connect(url, row_factory=dict_row) as db:
            _seed(db)
            postings = db.execute('select id::text, company, location, remote from postings').fetchall()
            db.commit()
            row = {'lat': 32, 'lng': 34, 'precision': 'city', 'source': 'fixture', 'resolved_at': '2026-09-22T00:00:00Z'}
            plan = {'postings': postings, 'posting_geo': [row | {'posting_id': id} for id in IDS[:2]], 'company_hq': []}
            receipt = tmp_path / 'receipt.json'
            assert apply_plan(db, plan, receipt) == {'posting_geo': 2, 'company_hq': 0}
            db.commit()
            assert apply_plan(db, plan, tmp_path / 'resume.json') == {'posting_geo': 0, 'company_hq': 0}
            db.execute('update posting_geo set lat=31 where posting_id=%s', (IDS[0],))
            db.commit()
            assert rollback_plan(db, json.loads(receipt.read_text())) == {'posting_geo': 1, 'company_hq': 0}
            assert db.execute('select lat from posting_geo where posting_id=%s', (IDS[0],)).fetchone()['lat'] == 31
            db.execute("update postings set location='changed' where id=%s", (IDS[0],))
            db.commit()
            with pytest.raises(ValueError, match='snapshot changed'):
                apply_plan(db, plan, tmp_path / 'stale.json')
            assert (tmp_path / 'stale.json').stat().st_size == 0  # Failed reservation cannot be reused.
            with pytest.raises(FileExistsError):
                apply_plan(db, plan, receipt)


def test_hq_plan_predicate_matches_sql_boundary():
    with migrated_database(Path(__file__).parents[1] / 'supabase/migrations', through=17) as url:
        with psycopg.connect(url) as db:
            for location in (None, '', '  ', ' Remote ', 'hybrid', 'onsite', 'on-site', 'worldwide', 'anywhere', 'Jerusalem', 'Tel Aviv', 'EMEA'):
                for remote in (None, False, True):
                    actual = db.execute('select posting_hq_eligible(%s,%s)', (location, remote)).fetchone()[0]
                    assert actual == hq_eligible({'location': location, 'remote': remote})
