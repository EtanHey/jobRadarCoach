"""A user's pipeline decision wins over automated relevance filtering."""
import json
import re
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
from scraper.description_backfill import backfill
from scraper.relevance import PURSUIT_STATUSES, refresh_gate
from test_support.postgres import database_url, migrated_database

MIGRATIONS = Path(__file__).parents[1] / 'supabase/migrations'
PURSUED = ['worth_checking', 'applied', 'screen', 'interview_technical',
           'interview_final', 'offer', 'contract', 'rejected']


@pytest.fixture
def db():
    with migrated_database(MIGRATIONS, through=33) as url, psycopg.connect(url) as connection:
        connection.execute((MIGRATIONS / '0034_pursued_relevance_gate.sql').read_text())
        connection.execute((MIGRATIONS / '0035_pursuit_gate_corrections.sql').read_text())
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


def fill_description(db, pid, jd):
    db.execute("update postings set source='lever',url='https://jobs.lever.co/synthetic/pursued' where id=%s", (pid,))
    assert backfill(db, fetcher=lambda _: jd)['stored'] == 1


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
    fill_description(db, pid, 'Build React products. ' * 20)
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
    fill_description(db, pid, 'Applicants must already live in the US. ' * 20)
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
    with migrated_database(MIGRATIONS, through=33) as url, psycopg.connect(url) as db:
        ids = []
        for status in PURSUED + ['new', 'seen', 'skipped', 'archived', 'not_relevant']:
            pid = posting(db, 'Build React products. ' * 20)
            pursue(db, pid, status)
            db.execute("update postings set relevance_gate='{\"version\":\"synthetic\",\"rule\":\"leadership-title-strict\"}'::jsonb where id=%s", (pid,))
            ids.append(pid)
        before_history = db.execute('select * from posting_status_history order by id').fetchall()
        db.execute((MIGRATIONS / '0034_pursued_relevance_gate.sql').read_text())
        db.execute((MIGRATIONS / '0035_pursuit_gate_corrections.sql').read_text())
        for pid in ids[:len(PURSUED)]:
            assert db.execute('select relevance_filtered from postings where id=%s', (pid,)).fetchone() == (False,)
        for pid in ids[len(PURSUED):]:
            assert db.execute('select relevance_filtered from postings where id=%s', (pid,)).fetchone() == (True,)
        assert db.execute('select * from posting_status_history order by id').fetchall() == before_history


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


@pytest.mark.parametrize('status', ['skipped', 'archived', 'not_relevant'])
@pytest.mark.parametrize('gated_first', [True, False])
def test_dismissed_role_must_pass_gate_before_selection(db, status, gated_first):
    pid = posting(db, 'Build React products. ' * 20)
    if gated_first:
        refresh_gate(db, posting_ids=[pid])
    pursue(db, pid, status)
    assert list_scoring_candidates(db, limit=10, posting_ids=[pid]) == []
    assert select_postings(db, limit=10, posting_ids=[pid]) == []
    assert db.execute('select relevance_filtered from postings where id=%s', (pid,)).fetchone() == (True,)
    assert db.execute("select id::text from board_postings(filter=>'not-scored')").fetchall() == [(pid,)]
    assert db.execute("select id from board_postings(filter=>'all')").fetchall() == []
    db.execute("update postings set title='Frontend Engineer' where id=%s", (pid,))
    assert list_scoring_candidates(db, limit=10, posting_ids=[pid]) == [pid]
    assert [r['id'] for r in select_postings(db, limit=10, posting_ids=[pid])] == [pid]


def add_score(db, pid):
    payload = dict(employer_type='direct', seniority_real=None, fit_score=72,
                   fit_tier='good', recommendation='apply', reasons=[], fit_line='',
                   fit_line_evidence_ids=[], luna_status='ok')
    labels = dict(role_type=None, seniority_match='unknown', remote_ok='unknown', red_flag_count=0)
    db.execute("insert into posting_scores(posting_id,score,brain,model,scorer_version,posting_sha256,profile_sha256,history_sha256,score_payload,labels) values(%s,72,'synthetic','synthetic','1',%s,%s,%s,%s::jsonb,%s::jsonb)",
               (pid, *(['a'*64]*3), json.dumps(payload), json.dumps(labels)))


@pytest.mark.parametrize('status', ['new', 'seen', 'skipped', 'archived', 'not_relevant'])
@pytest.mark.parametrize('residency', [False, True])
def test_scored_while_pursued_return_only_restores_residency(db, status, residency):
    jd = ('Applicants must already live in the US. ' if residency else '') + 'Build React products. ' * 20
    pid = posting(db, jd)
    refresh_gate(db, posting_ids=[pid])
    pursue(db, pid, 'applied')
    add_score(db, pid)
    pursue(db, pid, status)
    gate, filtered = db.execute('select relevance_gate,relevance_filtered from postings where id=%s', (pid,)).fetchone()
    assert filtered is residency
    assert gate['rule'] == ('already-us-resident' if residency else None)
    assert 'pursued_rule' not in gate


class GateRecordingConnection:
    def __init__(self, connection):
        self.connection = connection
        self.queries = []

    def transaction(self):
        return self.connection.transaction()

    def execute(self, query, params=()):
        self.queries.append(query)
        return self.connection.execute(query, params)


@pytest.mark.parametrize('title', ['Principal Engineer', 'Frontend Engineer'])
def test_unchanged_at_write_skips_gate_update_and_posting_lock(db, title):
    pid = posting(db, 'Build React products. ' * 20)
    db.execute('update postings set title=%s where id=%s', (title, pid))
    refresh_gate(db, posting_ids=[pid], at_write=True)
    before = db.execute('select ctid::text from postings where id=%s', (pid,)).fetchone()
    recorded = GateRecordingConnection(db)
    refresh_gate(recorded, posting_ids=[pid], at_write=True)
    assert not any('update public.postings' in q.lower() for q in recorded.queries)
    assert not any('for update' in q.lower() for q in recorded.queries)
    assert db.execute('select ctid::text from postings where id=%s', (pid,)).fetchone() == before


def test_sql_and_python_pursuit_sets_are_equal():
    sql = (MIGRATIONS / '0035_pursuit_gate_corrections.sql').read_text()
    predicates = re.findall(r"status (?:not )?in \(([^)]+)\)", sql)
    assert len(predicates) == 3
    assert PURSUIT_STATUSES == frozenset(PURSUED)
    for predicate in predicates:
        assert frozenset(re.findall(r"'([^']+)'", predicate)) == PURSUIT_STATUSES


@pytest.mark.parametrize('title', ['Principal Engineer', 'Frontend Engineer'])
def test_unchanged_rescrape_issues_no_gate_update(db, title):
    from scraper.database import persist_postings_with_disposition
    from test_support.test_cloud_relevance_gate import observation
    row = observation(title)
    persist_postings_with_disposition(db, [row], '2026-10-11T06:00:00Z')
    recorded = GateRecordingConnection(db)
    persist_postings_with_disposition(recorded, [row], '2026-10-11T06:01:00Z')
    assert not any('update public.postings' in q.lower() and 'relevance_gate' in q.lower()
                   for q in recorded.queries)
