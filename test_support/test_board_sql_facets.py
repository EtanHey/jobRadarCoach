"""Every facet combination matches the TS oracle on fictional, real-shaped rows."""
import itertools
import json
import os
import subprocess
from pathlib import Path
from uuid import UUID

import psycopg
from test_support.postgres import migrated_database

ROOT = Path(__file__).parents[1]


def test_board_sql_facets_match_typescript():
    locations = [None, "", " Remote / Anywhere ", "Hybrid position", "Tel Aviv-Yafo, Israel", "Ra’anana", "Remote, U.S.A.", "San Francisco, CA", "Fortville, IN", "Toronto, CA", "Hyderabad, IN", "Unknown City, CA", "London, UK", "San Francisco Bay Area", "New York City Metropolitan Area", "Austin, Texas Metropolitan Area", "fooIsrael", "éIsrael", "Israelé", "Seattle, wa", "Seattle, WA", "Worldwide work or remote role", "Remote\u00a0role", "Seattle\u00a0, WA", "Seattle,\u00a0WA", "\ufeffHybrid\ufeff", "New York , NY"]
    levels = [None, "", "Intern", "Junior", "entry graduate", "Intermediate", "Senior", "Director", "Staff Principal", "Mystery", "senior intern"]
    rows = []
    for i in range(132):
        rows.append(dict(id=str(UUID(int=i+1)), title=["Senior Engineer", "Internship", "Jr. Engineer", "Mid-level Developer", "Staff Engineer", "Engineering manager", "Unknown Engineer"][i % 7], company=f"Fictional studio {i}",
                         source=["synthetic-a", "synthetic-b"][(i // 4) % 2], location=locations[(i // 3) % len(locations)],
                         seniority=levels[i % len(levels)], work_mode=[None, "remote", "hybrid", "on-site"][i % 4], remote=[None, True, False][i % 3],
                         first_seen_at="2026-10-01T00:00:00Z", posted_at=None, stack=[], status="new", score=None, recommendation=None))
    base = dict(search="", source="", work_mode=None, location="", seniority="", availability="all", statuses=[], fit="", sort="found")
    cases = [{**base, "source": source, "work_mode": mode, "location": location, "seniority": level}
             for source, mode, location, level in itertools.product(["", "synthetic-a", "synthetic-b", "absent"], [None, "remote", "hybrid", "on-site"], ["", "israel", "united-states", "other"], ["", "non-senior", "Intern", "Junior", "Mid-level", "Senior", "Lead / Manager", "Staff / Principal", "Unknown"])]
    cases += [{**base, "remote": remote, "work_mode": mode} for remote, mode in itertools.product([True, False], [None, "hybrid"])]
    expected = json.loads(subprocess.run(["node", "--import", "tsx", "tests/fixtures/board-golden.ts"], cwd=ROOT / "ui", input=json.dumps(dict(rows=rows, cases=cases)), text=True, capture_output=True, check=True).stdout)
    with migrated_database(ROOT / "supabase/migrations", through=int(os.environ.get("P4F_TEST_THROUGH", "31"))) as url, psycopg.connect(url) as db:
        for row in rows:
            db.execute("insert into postings(id,source,external_id,url,title,company,location,seniority,work_mode,work_mode_source,remote,first_seen_at) values (%s,%s,%s,'https://example.test',%s,%s,%s,%s,%s,case when %s::text is not null then 'structured' end,%s,%s)", tuple(row[k] for k in ["id", "source", "id", "title", "company", "location", "seniority", "work_mode", "work_mode", "remote", "first_seen_at"]))
        db.execute("set local role service_role")
        for case, ids in zip(cases, expected, strict=True):
            actual = db.execute("select id from board_postings(filter=>'all',availability=>'all',sort=>'found',source=>%s,work_mode=>%s,location=>%s,seniority=>%s,remote=>%s)", (case["source"], case["work_mode"] or "", case["location"], case["seniority"], case.get("remote"))).fetchall()
            assert [str(row[0]) for row in actual] == ids, case
        # More than 1,000 newer nonmatching rows cannot conceal an old match.
        db.execute("reset role")
        db.execute("insert into postings(source,external_id,url,title,company,location,seniority,work_mode,work_mode_source,first_seen_at) select 'noise',i::text,'https://example.test','Senior Engineer',i::text,'London, UK','Senior','on-site','structured',now() from generate_series(1,1005) i")
        db.execute("set local role service_role")
        case = dict(source="synthetic-a",work_mode="hybrid",location="israel",seniority="non-senior")
        ids = db.execute("select id from board_postings(filter=>'all',availability=>'all',sort=>'found',source=>%s,work_mode=>%s,location=>%s,seniority=>%s)", tuple(case.values())).fetchall()
        oracle = cases.index({**base, **case})
        assert ids and [str(row[0]) for row in ids] == expected[oracle]
        for facet, value in case.items():
            single = {**base, facet: value}
            result = db.execute("select id from board_postings(filter=>'all',availability=>'all',sort=>'found',source=>%s,work_mode=>%s,location=>%s,seniority=>%s)", (single["source"], single["work_mode"] or "", single["location"], single["seniority"])).fetchall()
            assert result and [str(row[0]) for row in result] == expected[cases.index(single)]
        for role in ("anon", "authenticated", "service_role"):
            assert db.execute("select has_function_privilege(%s,'public.board_postings(text,text,text,text[],text,integer,text,text,text,text,text,boolean)','execute')", (role,)).fetchone() == (role == "service_role",)


def test_board_facets_rollback_restores_existing_rpc():
    with migrated_database(ROOT / "supabase/migrations", through=31) as url, psycopg.connect(url) as db:
        db.execute((ROOT / "supabase/rollbacks/0031_board_sql_facets.sql").read_text())
        assert db.execute("select pronargs from pg_proc where oid='public.board_postings(text,text,text,text[],text,integer,text)'::regprocedure").fetchone() == (7,)
        assert db.execute("select to_regprocedure('public.board_postings(text,text,text,text[],text,integer,text,text,text,text,text,boolean)')").fetchone() == (None,)
        assert db.execute("select to_regprocedure('public.board_location_group(text)')").fetchone() == (None,)
        for role in ("anon", "authenticated", "service_role"):
            assert db.execute("select has_function_privilege(%s,'public.board_postings(text,text,text,text[],text,integer,text)','execute')", (role,)).fetchone() == (role == "service_role",)
        db.execute("set local role service_role")
        assert db.execute("select count(*) from board_postings()").fetchone() == (0,)
