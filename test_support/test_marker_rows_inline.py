"""Marker projection parity, selective plans and hostile search-path safety."""

from itertools import product
from pathlib import Path
from uuid import UUID

import psycopg
import pytest
from psycopg import sql

from test_support.postgres import migrated_database

MIGRATIONS = Path(__file__).parents[1] / "supabase/migrations"
IDS = [str(UUID(int=n + 1)) for n in range(24)]


def _upgrade(db):
    # Isolate this performance migration: later migrations may deliberately
    # change archive/status semantics and must not enter the parity comparison.
    db.execute((MIGRATIONS / "0032_marker_rows_inline.sql").read_text())


def _seed(db):
    statuses = ("new", "seen", "worth_checking", "applied", "screen", "archived")
    alive = ('{}', '{"alive":true}', '{"alive":false}', '{"alive":"unknown"}')
    for n, posting_id in enumerate(IDS):
        db.execute("""insert into public.postings
            (id,source,external_id,url,title,company,location,remote,stack,raw_jd,
             first_seen_at,last_seen_at,liveness,relevance_gate)
            values (%s,'fixture',%s,'https://example.test','Engineer','Synthetic',
                    'Example City',%s,%s,'Requirements: Python',
                    now()-%s*interval '1 hour',now(),%s::jsonb,%s::jsonb)""",
            (posting_id, posting_id, n % 2 == 0, ["TypeScript"] if n % 2 else [],
             n * 48, alive[n % 4],
             '{"rule":"leadership-title-strict"}' if n % 3 == 0 else '{}'))
        if n != 23:
            db.execute("insert into public.posting_status(posting_id,status) values (%s,%s)",
                       (posting_id, statuses[n % len(statuses)]))
    db.execute("""insert into public.posting_geo(posting_id,lat,lng,precision,source)
                  values (%s,10,20,'city','synthetic')""", (IDS[1],))
    # Include validated score/extraction fixtures without personal data.
    from test_support.test_job_api import _seed as seed_scores
    seed_scores(db)
    db.execute("""insert into public.postings
        (id,source,external_id,url,title,company,first_seen_at,last_seen_at)
        select lpad(to_hex(n),32,'0')::uuid,'fixture',n::text,
               'https://example.test','Engineer','Synthetic',
               now()-interval '1 hour',now() from generate_series(1000,1102) n""")


def _poll_output(db, arguments):
    ordered_output, current = db.execute("""select
        (snapshot - 'current')::text, snapshot->'current'
        from (select public.get_new_roles_snapshot(
            %s,%s,%s::timestamptz,%s,%s::uuid[],%s::uuid[]) as snapshot) poll""",
        arguments).fetchone()
    # Incoming stays byte-identical. Only current is an unordered collection;
    # compare every marker field after sorting by its unique posting ID.
    return ordered_output, sorted(current, key=lambda marker: marker["id"])


def _snapshots(db):
    result = []
    since = db.execute("select now()-interval '50 days'").fetchone()[0]
    for view, availability, window in product(
        ("all", "not-scored", "new-for-me", "seen", "worth_checking", "applied", "screen", "archived"),
        ("all", "active", "inactive"), ("", "24h", "3d", "7d", "30d"),
    ):
        result.append(db.execute("select public.get_globe_markers(%s,%s,%s)::text",
                                 (view, availability, window)).fetchone()[0])
        for cohort in (None, [], IDS[1:5]):
            result.append(_poll_output(db, (view, availability, since, window, IDS, cohort)))
    return result


def test_ordered_rpc_outputs_and_canonical_current_match_after_upgrade():
    with migrated_database(MIGRATIONS, through=30) as url, psycopg.connect(url) as db:
        _seed(db)
        db.execute("set local role service_role")
        assert len(db.execute("select public.get_new_roles_snapshot('all','all',"
                              "now()-interval '2 hours')->'incoming'").fetchone()[0]) == 101
        before = _snapshots(db)
        db.execute("reset role")
        _upgrade(db)
        db.execute("set local role service_role")
        assert _snapshots(db) == before


def test_sparse_current_markers_match_after_descending_insert_upgrade():
    with migrated_database(MIGRATIONS, through=31) as url, psycopg.connect(url) as db:
        db.execute("""insert into public.postings
            (id,source,external_id,url,title,company,first_seen_at,last_seen_at)
            select lpad(to_hex(n),32,'0')::uuid,'fixture',n::text,
                   'https://example.test','Engineer','Synthetic',
                   timestamptz '2020-01-01Z',timestamptz '2026-10-11Z'
            from generate_series(5000,1,-1) n""")
        for table in ("postings", "posting_status", "posting_scores"):
            db.execute(sql.SQL("analyze public.{}").format(sql.Identifier(table)))
        ids = [str(UUID(int=n)) for n in (1, 1001, 2001, 3001, 4001)]
        arguments = ("all", "all", "2026-10-10Z", "", ids, [])
        db.execute("set local role service_role")
        before = _poll_output(db, arguments)
        assert [marker["id"] for marker in before[1]] == ids
        db.execute("reset role")
        _upgrade(db)
        db.execute("set local role service_role")
        assert _poll_output(db, arguments) == before


def _nodes(plan):
    yield plan
    for child in plan.get("Plans", []):
        yield from _nodes(child)


@pytest.mark.parametrize("cohort", [None, IDS[:8]], ids=["get", "post"])
def test_poll_incoming_cte_uses_first_seen_index(cohort):
    with migrated_database(MIGRATIONS, through=30) as url, psycopg.connect(url) as db:
        _upgrade(db)
        db.execute("""insert into public.postings
            (id,source,external_id,url,title,company,first_seen_at,last_seen_at)
            select lpad(to_hex(n),32,'0')::uuid,'fixture',n::text,
                   'https://example.test','Engineer','Synthetic',
                   case when n<=8 then timestamptz '2026-10-10Z'
                        else timestamptz '2020-01-01Z' end, timestamptz '2026-10-11Z'
            from generate_series(1,5000) n""")
        db.execute("analyze public.postings")
        db.execute("analyze public.posting_status")
        db.execute("analyze public.posting_scores")
        # Extract the actual incoming CTE, so changing the RPC cannot leave a
        # separately handwritten EXPLAIN test green.
        source = db.execute("select prosrc from pg_proc where oid="
                            "'public.get_new_roles_snapshot(text,text,timestamptz,text,uuid[],uuid[])'::regprocedure").fetchone()[0]
        incoming = source.split("), relevant_current as", 1)[0] + ") select * from incoming"
        db.execute("prepare marker_incoming(text,text,timestamptz,text,uuid[],uuid[]) as " + incoming)
        db.execute("set local role service_role")
        arguments = ("all", "all", "2026-10-09Z", "", [], cohort)
        plan = db.execute(sql.SQL("explain (analyze, buffers, format json) execute marker_incoming({})")
                          .format(sql.SQL(",").join(map(sql.Literal, arguments)))).fetchone()[0][0]["Plan"]
        nodes = list(_nodes(plan))
        print(cohort, plan)
        assert not any(n["Node Type"] == "Function Scan" for n in nodes), plan
        assert any(n.get("Index Name") == "postings_first_seen_at_id_idx" for n in nodes), plan
        assert plan["Actual Rows"] == 8


def test_marker_bindings_ignore_hostile_caller_search_path_and_preserve_grants():
    with migrated_database(MIGRATIONS, through=30) as url, psycopg.connect(url) as db:
        _seed(db)
        _upgrade(db)
        expected = db.execute("select marker::text from public.board_marker_rows() order by id").fetchall()
        db.execute("create schema hostile")
        db.execute("grant usage on schema hostile to service_role")
        db.execute("create table hostile.postings(id uuid)")
        db.execute("create temp table postings(id uuid)")
        db.execute("""create function hostile.jsonb_typeof(jsonb) returns text
                      language sql immutable as $$ select 'string'::text $$""")
        db.execute("""create function hostile.eq(text,text) returns boolean
                      language sql immutable as $$ select false $$""")
        db.execute("create operator hostile.= (leftarg=text,rightarg=text,function=hostile.eq)")
        db.execute("""create function hostile.extract(jsonb,text) returns text
                      language sql immutable as $$ select 'false'::text $$""")
        db.execute("create operator hostile.->> (leftarg=jsonb,rightarg=text,function=hostile.extract)")
        for routine in ("board_marker_rows()", "get_globe_markers(text,text,text)",
                        "get_new_roles_snapshot(text,text,timestamptz,text,uuid[],uuid[])"):
            for role in ("anon", "authenticated"):
                assert not db.execute("select has_function_privilege(%s,%s,'execute')",
                                      (role, "public." + routine)).fetchone()[0]
            assert db.execute("select has_function_privilege('service_role',%s,'execute')",
                              ("public." + routine,)).fetchone()[0]
        db.execute("set local role service_role")
        for search_path in ("hostile, public, pg_catalog", "pg_temp, hostile, public, pg_catalog", "''"):
            db.execute("select set_config('search_path',%s,true)", (search_path,))
            assert db.execute("select marker::text from public.board_marker_rows() order by id").fetchall() == expected
