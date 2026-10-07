"""Found windows filter before the cap in a disposable synthetic database."""
import os
from pathlib import Path
from uuid import UUID

import psycopg

from test_support.postgres import migrated_database


def test_found_windows_before_cap():
    root = Path(__file__).parents[1]
    through = int(os.environ.get('P3_TEST_THROUGH', '26'))
    with migrated_database(root / 'supabase/migrations', through=through) as url, psycopg.connect(url) as db:
        # One exact boundary, one just outside, and one older high-score candidate.
        for i, age in enumerate(['24 hours', '3 days', '7 days', '30 days', '31 days']):
            db.execute("insert into postings(id,source,external_id,url,title,company,first_seen_at,last_seen_at) "
                       "values (%s,'synthetic',%s,'https://example.test','Engineer',%s,now()-%s::interval,now())",
                       (UUID(int=i + 1), str(i), f'Example {i}', age))
        db.execute("set local role service_role")
        for window, count in [('24h', 1), ('3d', 2), ('7d', 3), ('30d', 4), ('', 5)]:
            rows = db.execute("select id from board_postings('all','all','','{}','found',1000,%s)", (window,)).fetchall()
            assert [r[0] for r in rows] == [UUID(int=i + 1) for i in range(count)]
        assert db.execute("select id from board_postings('all','all','','{}','fit',1,'24h')").fetchall() == [(UUID(int=1),)]
        assert db.execute("select has_function_privilege('anon','public.board_postings(text,text,text,text[],text,integer,text)','execute')").fetchone() == (False,)


def test_found_window_rollback_restores_six_argument_rpc():
    root = Path(__file__).parents[1]
    with migrated_database(root / 'supabase/migrations', through=26) as url, psycopg.connect(url) as db:
        db.execute("insert into postings(id,source,external_id,url,title,company) "
                   "values (%s,'synthetic','rollback','https://example.test','Engineer','Example')",
                   (UUID(int=1),))
        db.commit()
        db.execute((root / 'supabase/rollbacks/0026_board_found_within.sql').read_text())
        assert db.execute("select pronargs from pg_proc where oid='public.board_postings(text,text,text,text[],text,integer)'::regprocedure").fetchone() == (6,)
        assert db.execute("select to_regprocedure('public.board_postings(text,text,text,text[],text,integer,text)')").fetchone() == (None,)
        for role in ('anon', 'authenticated', 'service_role'):
            assert db.execute("select has_function_privilege(%s,'public.board_postings(text,text,text,text[],text,integer)','execute')", (role,)).fetchone() == (role == 'service_role',)
        db.execute('set local role service_role')
        assert db.execute("select id from public.board_postings('all','all','','{}','fit',1000)").fetchall() == [(UUID(int=1),)]
        db.execute('reset role')
        db.commit()
        db.execute((root / 'supabase/migrations/0026_board_found_within.sql').read_text())
        db.execute('set local role service_role')
        assert db.execute("select id from public.board_postings('all','all','','{}','fit',1000,'24h')").fetchall() == [(UUID(int=1),)]
