"""Single-statement globe snapshots use PostgreSQL MVCC, including the visit cutoff."""
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

from test_support.postgres import migrated_database
from test_support.test_job_api import _seed, IDS


def test_snapshot_is_complete_and_pins_mutations_and_visit_cutoff():
    with migrated_database(Path(__file__).parents[1] / 'supabase/migrations', through=16) as url:
        with psycopg.connect(url, row_factory=dict_row) as db:
            _seed(db)
            db.execute("insert into posting_status(posting_id,status) values (%s,'new'),(%s,'new')", (IDS[2], IDS[3]))
            db.execute("insert into visits(singleton,last_visit_at) values (true,'2020-01-01Z') on conflict (singleton) do update set last_visit_at=excluded.last_visit_at")
            db.commit()
            all_jobs = db.execute("select get_globe_snapshot('all','all') s").fetchone()['s']['jobs']
            by_id = {j['id']: j for j in all_jobs}
            assert by_id[IDS[0]]['posting_scores']['score'] == 95
            assert by_id[IDS[0]]['posting_extractions'] == {'posting_id': IDS[0]}
            assert db.execute("select get_globe_snapshot('applied','all') s").fetchone()['s']['jobs'][0]['id'] == IDS[0]
            db.execute("update postings set liveness='{\"alive\":false}' where id=%s", (IDS[0],))
            assert len(db.execute("select get_globe_snapshot('all','active') s").fetchone()['s']['jobs']) == 4
            assert db.execute("select get_globe_snapshot('all','inactive') s").fetchone()['s']['jobs'][0]['id'] == IDS[0]
            before = db.execute("select get_globe_snapshot('new-for-me','all') s").fetchone()['s']
            assert {j['id'] for j in before['jobs']} == {IDS[2], IDS[3]}
            # Data-modifying CTEs and STABLE functions see the same statement snapshot.
            during = db.execute("""with deletion as (delete from postings where id=%s returning id),
                reorder as (update postings set first_seen_at='2026-09-20Z' where id=%s returning id),
                cutoff as (update visits set last_visit_at='2040-01-01Z' returning singleton)
                select get_globe_snapshot('new-for-me','all') s""", (IDS[2], IDS[3])).fetchone()['s']
            assert during == before
            assert db.execute("select get_globe_snapshot('new-for-me','all') s").fetchone()['s'] == {'jobs': [], 'geo': []}
            db.execute("""insert into postings(source,external_id,url,title,company)
                select 'fixture',i::text,'https://example.test/'||i,'Engineer','Example' from generate_series(1,1007) i""")
            result = db.execute("select get_globe_snapshot('all','all') s").fetchone()['s']
            assert len(result['jobs']) == 1011
            for role in ('anon', 'authenticated'):
                assert not db.execute("select has_function_privilege(%s,'public.get_globe_snapshot(text,text)','execute') ok", (role,)).fetchone()['ok']
            db.execute('set local role service_role')
            assert len(db.execute("select get_globe_snapshot('all','all') s").fetchone()['s']['jobs']) == 1011
