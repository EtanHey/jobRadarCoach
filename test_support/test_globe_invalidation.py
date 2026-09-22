"""Posting input edits must retire obsolete coordinates in the writer transaction."""

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from time import monotonic, sleep

import psycopg
import pytest
from psycopg import sql
from psycopg.rows import dict_row

from scraper.database import POSTING_UPSERT
from scripts.globe_geocode import apply_plan, rollback_plan
from test_support.postgres import migrated_database
from test_support.test_globe_receipts import plan_for
from test_support.test_job_api import IDS, _seed

MIGRATIONS = Path(__file__).parents[1] / "supabase/migrations"
HQ = {
    "company": "Acme",
    "city": "New York",
    "country": "US",
    "lat": 40,
    "lng": -74,
    "source": "https://example.test/hq | nominatim:osm:node:1",
    "resolved_at": "2026-09-22T00:00:00Z",
}


@pytest.fixture
def database():
    with migrated_database(MIGRATIONS, through=18) as url:
        with psycopg.connect(url, row_factory=dict_row) as db:
            _seed(db)
            db.execute("select set_status(%s,'interview_technical',null)", (IDS[0],))
            db.execute(
                "insert into application_history(company,role,application_date) values ('Acme','Engineer','2026-09-22')"
            )
            db.commit()
            db.execute("set role service_role")
            db.commit()
            yield url, db
            # Session role must not affect disposable database teardown.
            db.rollback()
            db.execute("reset role")
            db.commit()


def rows(db, table):
    return db.execute(
        sql.SQL(
            "select to_jsonb(t) r from public.{} t order by to_jsonb(t)::text"
        ).format(sql.Identifier(table))
    ).fetchall()


def geo(db):
    return db.execute("select get_globe_snapshot('all','all') s").fetchone()["s"]["geo"]


def seed_geo(db, tmp_path, hq=False):
    plan = plan_for(db, IDS[:2])
    if hq:
        plan["company_hq"] = [HQ]
    path = tmp_path / "apply.json"
    apply_plan(db, plan, path)
    return path, json.loads(path.read_text())


@pytest.mark.parametrize(
    "field,before,after",
    [
        ("location", "Tel Aviv", "Haifa"),
        ("location", "Tel Aviv", None),
        ("location", None, "Haifa"),
        ("company", "Acme", "Changed Company"),
        ("remote", None, True),
        ("remote", None, False),
        ("remote", True, None),
        ("remote", False, None),
        ("remote", True, False),
        ("remote", False, True),
    ],
)
def test_changed_inputs_remove_only_owned_point_in_same_transaction(
    database, tmp_path, field, before, after
):
    _, db = database
    update = sql.SQL("update public.postings set {}=%s where id=%s").format(
        sql.Identifier(field)
    )
    db.execute(update, (before, IDS[0]))
    db.commit()
    path, receipt = seed_geo(db, tmp_path)
    original_file = path.read_bytes()
    preserved = {
        table: rows(db, table)
        for table in (
            "posting_status",
            "posting_status_history",
            "application_history",
            "posting_scores",
            "posting_extractions",
            "company_hq",
            "globe_geo_applies",
        )
    }
    untouched = [r for r in rows(db, "postings") if r["r"]["id"] != IDS[0]]
    other_geo = [r for r in rows(db, "posting_geo") if r["r"]["posting_id"] != IDS[0]]
    assert {r["posting_id"] for r in geo(db)} == set(IDS[:2])
    db.execute("savepoint posting_edit")
    db.execute(update, (after, IDS[0]))
    assert rows(db, "posting_geo") == other_geo
    assert {r["posting_id"] for r in geo(db)} == {IDS[1]}
    assert (
        db.execute("select * from get_job_geo(%s::uuid[])", ([IDS[0]],)).fetchall()
        == []
    )
    for table, original in preserved.items():
        assert rows(db, table) == original
    assert [r for r in rows(db, "postings") if r["r"]["id"] != IDS[0]] == untouched
    assert len(rows(db, "postings")) == 5
    db.execute("rollback to savepoint posting_edit")
    assert {r["posting_id"] for r in geo(db)} == set(IDS[:2])
    db.execute(update, (after, IDS[0]))
    db.commit()
    assert {r["posting_id"] for r in geo(db)} == {IDS[1]}
    db.commit()
    assert rollback_plan(db, receipt) == {"posting_geo": 1, "company_hq": 0}
    assert rows(db, "globe_geo_applies") == preserved["globe_geo_applies"]
    assert path.read_bytes() == original_file
    assert path.stat().st_mode & 0o777 == 0o400


@pytest.mark.parametrize("nullable", [False, True])
def test_same_values_and_unrelated_scraper_upsert_preserve_geo(
    database, tmp_path, nullable
):
    _, db = database
    if nullable:
        db.execute(
            "update postings set location=null,remote=null where id=%s", (IDS[0],)
        )
        db.commit()
    seed_geo(db, tmp_path)
    original = rows(db, "posting_geo")
    db.execute(
        "update postings set location=location,company=company,remote=remote,title='Retitled',raw_jd='Changed JD' where id=%s",
        (IDS[0],),
    )
    db.execute("update postings set last_seen_at=now() where id=%s", (IDS[0],))
    db.execute(
        POSTING_UPSERT,
        (
            "fixture",
            "one",
            "https://example.test/one",
            "Retitled",
            "Acme",
            None,
            None,
            None,
            [],
            None,
            None,
            None,
            None,
            "2026-09-22Z",
            "2026-09-22Z",
            "{}",
            False,
        ),
    )
    assert rows(db, "posting_geo") == original
    db.commit()
    assert rows(db, "posting_geo") == original


def test_real_scraper_upsert_and_current_hq_fallback(database, tmp_path):
    _, db = database
    path, receipt = seed_geo(db, tmp_path, hq=True)
    hq_before = rows(db, "company_hq")
    db.execute(
        POSTING_UPSERT,
        (
            "fixture",
            "one",
            "https://example.test/one",
            "Engineer",
            "Acme",
            "Remote",
            True,
            None,
            [],
            None,
            None,
            None,
            None,
            "2026-09-22Z",
            "2026-09-22Z",
            "{}",
            False,
        ),
    )
    served = {r["posting_id"]: r for r in geo(db)}
    assert served[IDS[0]]["precision"] == "hq"
    assert (served[IDS[0]]["lat"], served[IDS[0]]["lng"]) == (40, -74)
    assert [r["r"]["posting_id"] for r in rows(db, "posting_geo")] == [IDS[1]]
    db.execute(
        "update postings set location='Paris',remote=false where id=%s", (IDS[0],)
    )
    assert {r["posting_id"] for r in geo(db)} == {IDS[1]}
    db.execute(
        "update postings set company='Different',remote=true where id=%s", (IDS[0],)
    )
    assert {r["posting_id"] for r in geo(db)} == {IDS[1]}
    assert rows(db, "company_hq") == hq_before
    assert json.loads(path.read_text()) == receipt


def test_security_contract_stays_owner_only(database):
    _, db = database
    for role in ("anon", "authenticated", "public"):
        for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE"):
            assert not db.execute(
                "select has_table_privilege(%s,'public.posting_geo',%s) ok",
                (role, privilege),
            ).fetchone()["ok"]
        assert not db.execute(
            "select has_function_privilege(%s,'public.invalidate_posting_geo()', 'EXECUTE') ok",
            (role,),
        ).fetchone()["ok"]
    assert db.execute(
        "select has_function_privilege('service_role','public.invalidate_posting_geo()','EXECUTE') ok"
    ).fetchone()["ok"]
    function = db.execute(
        "select prosecdef,proconfig from pg_proc where oid='public.invalidate_posting_geo()'::regprocedure"
    ).fetchone()
    assert not function["prosecdef"]
    assert function["proconfig"] == ['search_path=""']
    assert db.execute(
        "select relrowsecurity from pg_class where oid='public.posting_geo'::regclass"
    ).fetchone()["relrowsecurity"]


def wait_blocked(db, pid):
    deadline = monotonic() + 5
    while monotonic() < deadline:
        if db.execute("select cardinality(pg_blocking_pids(%s)) n", (pid,)).fetchone()[
            "n"
        ]:
            return
        sleep(0.01)
    pytest.fail("concurrent operation did not wait on the posting lock")


def test_update_waits_for_apply_then_invalidates_its_coordinates(
    database, tmp_path, monkeypatch
):
    import scripts.globe_receipts as receipts

    url, db = database
    plan = plan_for(db)
    entered, release = Event(), Event()
    publish = receipts.publish_receipt

    def pause(file, receipt):
        entered.set()
        assert release.wait(10)
        publish(file, receipt)

    monkeypatch.setattr(receipts, "publish_receipt", pause)
    path = tmp_path / "concurrent.json"
    with (
        psycopg.connect(url, row_factory=dict_row) as updater,
        ThreadPoolExecutor(2) as pool,
    ):
        updater.execute("set role service_role")
        updater.commit()
        applying = pool.submit(apply_plan, db, plan, path)
        try:
            assert entered.wait(5)
            editing = pool.submit(
                updater.execute,
                "update postings set location='Paris' where id=%s",
                (IDS[0],),
            )
            with psycopg.connect(url, row_factory=dict_row) as observer:
                wait_blocked(observer, updater.info.backend_pid)
        finally:
            release.set()
        assert applying.result(timeout=5)["posting_geo"] == 1
        editing.result(timeout=5)
        assert geo(updater) == []
        updater.commit()
    assert geo(db) == []
    db.commit()
    assert rollback_plan(db, json.loads(path.read_text())) == {
        "posting_geo": 0,
        "company_hq": 0,
    }


def test_apply_waits_for_update_then_rejects_stale_plan(database, tmp_path):
    url, db = database
    plan = plan_for(db)
    db.execute("update postings set location='Paris' where id=%s", (IDS[0],))
    path = tmp_path / "stale.json"
    with (
        psycopg.connect(url, row_factory=dict_row) as applying,
        ThreadPoolExecutor(1) as pool,
    ):
        applying.execute("set role service_role")
        applying.commit()
        future = pool.submit(apply_plan, applying, plan, path)
        try:
            wait_blocked(db, applying.info.backend_pid)
        finally:
            db.commit()
        with pytest.raises(ValueError, match="Posting snapshot changed"):
            future.result(timeout=5)
    assert geo(db) == []
    assert rows(db, "globe_geo_applies") == []
    assert path.read_bytes() == b""
