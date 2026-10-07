"""Projection RPCs preserve archive, cursor, window, availability and complete cohorts."""
from pathlib import Path
from uuid import UUID
import json
import psycopg
from test_support.postgres import migrated_database
def test_slim_snapshots(capsys):
    migrations = Path(__file__).parents[1] / "supabase/migrations"
    with migrated_database(migrations, through=29) as url, psycopg.connect(url, autocommit=True) as db:
        ids = [str(UUID(int=n + 1)) for n in range(1010)]
        for n, id in enumerate(ids):
            db.execute("""insert into postings(id,source,external_id,url,title,company,first_seen_at,last_seen_at,liveness,relevance_gate)
              values(%s,'fixture',%s,'https://example.test','Engineer',%s,
                now()-case when %s=0 then interval '40 days' else interval '1 hour' end,now(),%s::jsonb,%s::jsonb)""",
                (id,id,f"Synthetic {n}",n,'{"alive":false}' if n==1 else '{}',
                 '{"rule":"leadership-title-strict"}' if n==2 else '{}'))
            db.execute("insert into posting_status(posting_id,status) values(%s,%s)",(id,'seen' if n==3 else 'new'))
        db.execute("delete from posting_status where posting_id=%s",(ids[-1],))
        db.execute("update postings set company=' Ｓｙｎｔｈｅｔｉｃ ' where id=%s",(ids[0],))
        db.execute("update postings set company='synthetic' where id=%s",(ids[1],))
        before = db.execute("select get_globe_snapshot('all','all')").fetchone()[0]
        db.execute((migrations / "0030_globe_poll_projection.sql").read_text())
        db.execute("set role service_role")
        globe = lambda f,a,w='': db.execute("select get_globe_markers(%s,%s,%s)",(f,a,w)).fetchone()[0]
        after = globe('all','all')
        assert len(before['jobs']) == len(after['jobs']) == 1009
        assert all('score_payload' not in str(row) and 'list_metadata' not in row for row in after['jobs'])
        assert {row['id'] for row in globe('all','all','24h')['jobs']} == set(ids)-{ids[0],ids[2]}
        assert [row['id'] for row in globe('all','inactive')['jobs']] == [ids[1]]
        assert len(globe('all','active')['jobs']) == 1008
        assert ids[-1] in {row['id'] for row in globe('new-for-me','all')['jobs']}
        assert [row['id'] for row in globe('not-scored','all')['jobs']] == [ids[2]]
        assert ids[3] not in {row['id'] for row in globe('new-for-me','all')['jobs']}
        poll = lambda f,a,w='': db.execute("select get_new_roles_snapshot(%s,%s,now()-interval '2 hours',%s,%s::uuid[])",(f,a,w,[ids[0]])).fetchone()[0]
        assert len(poll('all','all')['incoming']) == 101
        assert [row['id'] for row in poll('all','inactive')['current']] == [ids[0]]
        cursor=db.execute('select first_seen_at from postings where id=%s',(ids[1],)).fetchone()[0]
        assert db.execute("select get_new_roles_snapshot('all','inactive',%s,'','{}')",(cursor,)).fetchone()[0]['incoming']==[]
        assert [row['id'] for row in poll('all','inactive','24h')['incoming']] == [ids[1]]
        assert [row['id'] for row in poll('not-scored','all')['incoming']] == [ids[2]]
        assert db.execute("select get_new_roles_snapshot('all','all',now(),'','{}')").fetchone()[0]['incoming'] == []
        assert db.execute("select has_function_privilege('anon','get_new_roles_snapshot(text,text,timestamptz,text,uuid[])','execute')").fetchone() == (False,)
        print("synthetic globe DB JSON bytes:",len(json.dumps(before,separators=(',',':')).encode()),"->",len(json.dumps(after,separators=(',',':')).encode()))
