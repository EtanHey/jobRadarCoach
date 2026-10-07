"""Archive isolation before LIMIT, globe counts and idempotent override: real SQL."""
from pathlib import Path
from uuid import uuid4
import psycopg
from test_support.postgres import migrated_database


def test_archive_exclusion_and_score_anyway():
    migrations = Path(__file__).parents[1] / 'supabase/migrations'
    with migrated_database(migrations, through=max(int(p.name[:4]) for p in migrations.glob('[0-9][0-9][0-9][0-9]_*.sql'))) as url, psycopg.connect(url) as db:
        ids = [str(uuid4()), str(uuid4())]
        for id, filtered in zip(ids, [True, False]):
            db.execute("insert into postings(id,source,external_id,url,title,company,relevance_gate) values(%s,'synthetic',%s,'https://example.test/job','Engineer','Example',%s::jsonb)", (id,id,'{"version":"test","rule":"leadership-title-strict"}' if filtered else '{}'))
            db.execute("insert into posting_status(posting_id,status) values(%s,'new')", (id,))
        for filter in ['all', 'new-for-me', 'seen', 'not-scored']:
            if filter == 'seen':db.execute("update posting_status set status='seen'")
            rows = db.execute("select id::text from board_postings(%s,'all','','{}','found',1,'')",(filter,)).fetchall()
            assert rows == [(ids[0] if filter == 'not-scored' else ids[1],)]
            globe = db.execute("select get_globe_snapshot(%s,'all')",(filter,)).fetchone()[0]
            assert [r['id'] for r in globe['jobs']] == [ids[0] if filter == 'not-scored' else ids[1]]
        for _ in range(2):
            assert db.execute('select score_anyway(%s)',(ids[0],)).fetchone() == (True,)
        assert db.execute("select count(*) from board_postings('not-scored','all')").fetchone() == (0,)
        assert db.execute("select count(*) from board_postings('all','all')").fetchone() == (2,)
        assert db.execute('select score_anyway(%s)',(str(uuid4()),)).fetchone() == (False,)
