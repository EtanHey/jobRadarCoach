"""New-for-me has the same status membership whatever the retired visit timestamp."""
from pathlib import Path

import psycopg

from test_support.postgres import migrated_database

MIGRATIONS = Path(__file__).parents[1] / "supabase/migrations"


def test_new_for_me_is_status_based_even_with_a_future_visit():
    with migrated_database(MIGRATIONS, through=23) as url, psycopg.connect(url) as db:
        ids = [row[0] for row in db.execute("insert into postings(source,external_id,url,title,company,posted_at,first_seen_at) select 'fixture', i::text, 'https://example.test/'||i, 'Engineer', 'Fixture', null, '2000-01-01Z' from generate_series(1,3) i returning id")]
        db.execute("insert into posting_status(posting_id,status) values (%s,'new'),(%s,'seen')", ids[:2])
        for visit in ('1990-01-01Z', '2040-01-01Z'):
            db.execute("insert into visits(singleton,last_visit_at) values(true,%s) on conflict(singleton) do update set last_visit_at=excluded.last_visit_at", (visit,))
            snapshot = db.execute("select get_globe_snapshot('new-for-me','all')").fetchone()[0]
            assert [job['id'] for job in snapshot['jobs']] == [str(ids[0])]
