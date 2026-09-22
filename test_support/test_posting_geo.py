"""Real PostgreSQL tests in disposable sibling databases; coordinates are fixtures."""
from pathlib import Path

import psycopg
import pytest
from psycopg.rows import dict_row

from test_support.postgres import migrated_database
from test_support.test_job_api import _seed, IDS


def test_geo_validation_fallback_and_privileges():
    with migrated_database(Path(__file__).parents[1] / 'supabase/migrations', through=16) as url:
        with psycopg.connect(url, row_factory=dict_row) as db:
            _seed(db)
            db.execute("insert into company_hq(company,lat,lng,city,country,source) values ('Acme',32,34,'City','Country','https://example.test/hq')")
            db.execute("insert into posting_geo(posting_id,lat,lng,precision,source) values (%s,31,35,'city','nominatim')", (IDS[1],))
            db.commit()
            rows = db.execute('select * from get_job_geo(%s)', (IDS,)).fetchall()
            assert {str(r['posting_id']): r['precision'] for r in rows} == {IDS[0]: 'hq', IDS[1]: 'city'}
            assert db.execute('select * from get_job_geo(%s)', ([],)).fetchall() == []
            for lat, lng, precision in [(91,0,'city'), (0,-181,'city'), (float('nan'),0,'city'), (0,float('inf'),'city'), (0,0,'office')]:
                with pytest.raises(psycopg.errors.CheckViolation):
                    db.execute("insert into posting_geo(posting_id,lat,lng,precision,source) values (%s,%s,%s,%s,'test')", (IDS[2],lat,lng,precision))
                db.rollback()
            db.execute("insert into posting_geo(posting_id,lat,lng,precision,source) values (%s,30,33,'region','nominatim')", (IDS[0],))
            assert db.execute('select precision from get_job_geo(%s)', ([IDS[0]],)).fetchone()['precision'] == 'region'
            db.execute('delete from postings where id=%s', (IDS[1],))
            assert db.execute('select * from get_job_geo(%s)', ([IDS[1]],)).fetchall() == []
            for role in ('anon', 'authenticated'):
                assert not db.execute("select has_function_privilege(%s,'public.get_job_geo(uuid[])','execute') ok", (role,)).fetchone()['ok']
                for table in ('posting_geo','company_hq'):
                    assert not db.execute("select has_table_privilege(%s,%s,'select') ok", (role,table)).fetchone()['ok']
            db.execute('set local role service_role')
            assert len(db.execute('select * from get_job_geo(%s)', (IDS,)).fetchall()) == 1
