"""A user's pipeline decision wins over automated relevance filtering."""
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from queue import Queue
import time
from uuid import uuid4

import psycopg
from psycopg.conninfo import make_conninfo
import pytest

from classifier.persistence import list_scoring_candidates
from classifier.test_core import profile_snapshot
from extractor.job import select_postings
from scraper.relevance import refresh_gate
from test_support.postgres import database_url, migrated_database

MIGRATIONS = Path(__file__).parents[1] / 'supabase/migrations'
PURSUED = ['worth_checking', 'applied', 'screen', 'interview_technical',
           'interview_final', 'offer', 'contract', 'rejected', 'archived', 'not_relevant']


@pytest.fixture
def db():
    with migrated_database(MIGRATIONS, through=30) as url, psycopg.connect(url) as connection:
        connection.execute((MIGRATIONS / '0033_pursued_relevance_gate.sql').read_text())
        for field, value in profile_snapshot().items():
            if field not in {'people', 'connectors'}:
                connection.execute('insert into profile(field,value) values(%s,%s::jsonb) on conflict(field) do update set value=excluded.value', (field, json.dumps(value)))
        yield connection


def posting(db, jd=None):
    pid = str(uuid4())
    db.execute("insert into postings(id,source,external_id,url,title,company,raw_jd) values(%s,'synthetic',%s,'https://example.test/pursued','Principal Engineer','Synthetic',%s)", (pid, pid, jd))
    db.execute('insert into posting_status(posting_id) values(%s)', (pid,))
    return pid


def pursue(db, pid, status):
    db.execute('select set_status(%s,%s,%s)', (pid, status, 'Synthetic employer rejection' if status == 'rejected' else None))


def assert_visible(db, pid, status):
    assert db.execute('select relevance_filtered from postings where id=%s', (pid,)).fetchone() == (False,)
    assert db.execute('select id::text from board_postings(filter=>%s)', (status,)).fetchall() == [(pid,)]
    assert db.execute("select get_globe_snapshot(%s,'active')", (status,)).fetchone()[0]['jobs'][0]['id'] == pid
    assert db.execute("select get_globe_markers(%s,'active')", (status,)).fetchone()[0]['jobs'][0]['id'] == pid
    snapshot = db.execute("select get_new_roles_snapshot(%s,'active','2000-01-01Z','',%s::uuid[])", (status, [pid])).fetchone()[0]
    assert snapshot['incoming'][0]['id'] == pid
    assert snapshot['current'][0]['id'] == pid
    assert db.execute("select id from board_postings(filter=>'not-scored')").fetchall() == []


@pytest.mark.parametrize('status', PURSUED)
@pytest.mark.parametrize('stage', ['extract', 'score'])
def test_pursued_before_description_backfill_survives_gate_and_selection(db, status, stage):
    pid = posting(db)
    pursue(db, pid, status)
    db.execute("update postings set raw_jd=repeat('Build React products. ',20) where id=%s", (pid,))
    selected = (list_scoring_candidates(db, limit=10, posting_ids=[pid]) if stage == 'score'
                else [r['id'] for r in select_postings(db, limit=10, posting_ids=[pid])])
    assert selected == [pid]
    assert_visible(db, pid, status)


@pytest.mark.parametrize('status', PURSUED)
def test_already_gated_role_becomes_visible_on_pursue(db, status):
    pid = posting(db, 'Build React products. ' * 20)
    refresh_gate(db, posting_ids=[pid])
    assert db.execute('select relevance_filtered from postings where id=%s', (pid,)).fetchone() == (True,)
    pursue(db, pid, status)
    assert_visible(db, pid, status)
    refresh_gate(db, posting_ids=[pid], at_write=True)
    assert_visible(db, pid, status)


def test_applied_to_screen_remains_visible_after_backfill(db):
    pid = posting(db)
    pursue(db, pid, 'applied')
    pursue(db, pid, 'screen')
    db.execute("update postings set raw_jd=repeat('Applicants must already live in the US. ',5) where id=%s", (pid,))
    refresh_gate(db, posting_ids=[pid])
    assert_visible(db, pid, 'screen')


@pytest.mark.parametrize('status', ['new', 'seen'])
def test_return_to_discovery_restores_unchanged_gate(db, status):
    pid = posting(db, 'Build React products. ' * 20)
    refresh_gate(db, posting_ids=[pid])
    pursue(db, pid, 'worth_checking')
    assert_visible(db, pid, 'worth_checking')
    pursue(db, pid, status)
    assert db.execute('select relevance_filtered from postings where id=%s', (pid,)).fetchone() == (True,)
    assert db.execute('select id from board_postings(filter=>%s)', (status,)).fetchall() == []


def test_saved_rule_is_invalidated_by_changed_description(db):
    pid = posting(db, 'Build React products. ' * 20)
    refresh_gate(db, posting_ids=[pid])
    pursue(db, pid, 'worth_checking')
    db.execute("update postings set title='Frontend Engineer' where id=%s", (pid,))
    pursue(db, pid, 'new')
    refresh_gate(db, posting_ids=[pid])
    assert db.execute('select relevance_filtered from postings where id=%s', (pid,)).fetchone() == (False,)


def test_explicit_override_survives_pursuit_and_return(db):
    pid = posting(db, 'Build React products. ' * 20)
    refresh_gate(db, posting_ids=[pid])
    pursue(db, pid, 'worth_checking')
    db.execute('select score_anyway(%s)', (pid,))
    pursue(db, pid, 'seen')
    gate, filtered = db.execute('select relevance_gate,relevance_filtered from postings where id=%s', (pid,)).fetchone()
    assert gate['override'] and gate['score_requested'] and not filtered


def test_service_role_direct_status_insert_clears_gate(db):
    pid = posting(db, 'Build React products. ' * 20)
    refresh_gate(db, posting_ids=[pid])
    db.execute('delete from posting_status where posting_id=%s', (pid,))
    db.execute('set local role service_role')
    db.execute("insert into posting_status(posting_id,status) values(%s,'worth_checking')", (pid,))
    assert_visible(db, pid, 'worth_checking')


def test_migration_repairs_existing_pursued_rows_only():
    with migrated_database(MIGRATIONS, through=30) as url, psycopg.connect(url) as db:
        ids = []
        for status in PURSUED + ['new', 'seen']:
            pid = posting(db, 'Build React products. ' * 20)
            pursue(db, pid, status)
            db.execute("update postings set relevance_gate='{\"version\":\"synthetic\",\"rule\":\"leadership-title-strict\"}'::jsonb where id=%s", (pid,))
            ids.append(pid)
        db.execute((MIGRATIONS / '0033_pursued_relevance_gate.sql').read_text())
        for pid in ids[:len(PURSUED)]:
            assert db.execute('select relevance_filtered from postings where id=%s', (pid,)).fetchone() == (False,)
        for pid in ids[len(PURSUED):]:
            assert db.execute('select relevance_filtered from postings where id=%s', (pid,)).fetchone() == (True,)
        assert db.execute('select count(*) from posting_status_history').fetchone()[0] == 23


def test_pursue_wins_when_gate_waits_for_posting_lock(db):
    pid = posting(db, 'Build React products. ' * 20)
    db.commit()
    db.execute('select id from postings where id=%s for update', (pid,))
    backend = Queue()
    def gate_worker():
        # info.dsn strips credentials; retain the disposable server's auth.
        with psycopg.connect(make_conninfo(database_url(), dbname=db.info.dbname), autocommit=True) as worker:
            backend.put(worker.info.backend_pid)
            refresh_gate(worker, posting_ids=[pid])
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(gate_worker)
        worker_pid = backend.get(timeout=5)
        try:
            deadline = time.monotonic() + 5
            while db.execute('select wait_event_type from pg_stat_activity where pid=%s', (worker_pid,)).fetchone() != ('Lock',):
                assert time.monotonic() < deadline, 'gate did not reach the posting lock'
                db.execute('select pg_stat_clear_snapshot()')
                time.sleep(0.01)
            pursue(db, pid, 'worth_checking')
            db.commit()
        finally:
            db.rollback()
        future.result(timeout=5)
    assert_visible(db, pid, 'worth_checking')
