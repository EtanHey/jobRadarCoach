"""Retired SQL entry points disappear without removing live cross-repo RPCs."""
from pathlib import Path

import psycopg

from test_support.postgres import migrated_database

MIGRATIONS = Path(__file__).parents[1] / "supabase/migrations"
LATEST = max(int(p.name[:4]) for p in MIGRATIONS.glob("[0-9][0-9][0-9][0-9]_*.sql"))


def test_retired_objects_are_absent_and_live_rpcs_still_work():
    with migrated_database(MIGRATIONS, through=LATEST) as url, psycopg.connect(url) as db:
        for signature in ("list_new_for_me()", "list_jobs(boolean,integer,integer,text,text,text)", "set_seen(uuid,boolean)"):
            assert db.execute("select to_regprocedure(%s)", ("public." + signature,)).fetchone() == (None,)
        assert db.execute("select to_regclass('public.heartbeat')").fetchone() == (None,)
        [identity] = db.execute("insert into postings(source,external_id,url,title,company) values ('fixture','cleanup','https://example.test/cleanup','Engineer','Fixture') returning id").fetchone()
        db.execute("set local role service_role")
        assert db.execute("select status,seen from mark_seen(%s)", (identity,)).fetchone() == ("seen", True)
        assert db.execute("select * from get_job_geo(%s)", ([identity],)).fetchall() == []
        assert len(db.execute("select get_globe_snapshot('all','all')").fetchone()[0]['jobs']) == 1
