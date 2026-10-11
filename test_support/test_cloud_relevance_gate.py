"""Cloud persistence must commit the gate before any Mac analysis runs."""
import json
from pathlib import Path

import psycopg
import pytest

from scraper.database import persist_postings_with_disposition
from scraper.description_backfill import backfill
from scraper.relevance import VERSION
from test_support.postgres import migrated_database


@pytest.fixture
def db():
    with migrated_database(Path(__file__).parents[1] / 'supabase/migrations', through=30) as url:
        with psycopg.connect(url, autocommit=True) as connection:
            connection.execute((Path(__file__).parents[1] / 'supabase/migrations/0033_preserve_relevance_owner_intent.sql').read_text())
            yield connection


def observation(title='Principal Engineer', jd='Build React and TypeScript products. ' * 5):
    return dict(source='synthetic', id='cloud-gate', title=title, jd_text=jd,
                company='Synthetic', url='https://example.test/cloud-gate')


def write(db, row):
    return persist_postings_with_disposition(db, [row], '2026-10-11T06:00:00Z')


@pytest.mark.parametrize('jd', [None, 'Build React and TypeScript products. ' * 5])
@pytest.mark.parametrize('title,filtered', [('Principal Engineer', True), ('Frontend Engineer', False)])
def test_cloud_insert_is_gated_before_board_and_poll_reads(db, title, filtered, jd):
    receipt = write(db, observation(title, jd))
    [pid] = receipt['inserted_posting_ids']
    assert receipt['observed_posting_ids'] == [pid]
    assert db.execute('select relevance_filtered,relevance_gate from postings where id=%s',
                      (pid,)).fetchone() == (filtered, dict(version=VERSION, rule='leadership-title-strict' if filtered else None))
    for view in ['all', 'new-for-me', 'seen', 'not-scored']:
        visible = filtered if view == 'not-scored' else not filtered and view != 'seen'
        assert bool(db.execute('select id from board_postings(filter=>%s)', (view,)).fetchall()) == visible
        snapshot = db.execute("select get_new_roles_snapshot(%s,'active','2026-10-11T05:00:00Z')", (view,)).fetchone()[0]
        assert bool(snapshot['incoming']) == visible


def test_cloud_upsert_reclassifies_changed_text_and_retained_jd(db):
    row = observation('Frontend Engineer')
    [pid] = write(db, row)['inserted_posting_ids']
    rejected_jd = 'Applicants must already live in the US. ' + row['jd_text']
    for changed, filtered in [({**row, 'jd_text': rejected_jd}, True),
                              ({**row, 'jd_text': None}, True), (row, False)]:
        assert write(db, changed)['inserted_posting_ids'] == []
        assert db.execute('select relevance_filtered from postings where id=%s', (pid,)).fetchone() == (filtered,)


@pytest.mark.parametrize('protection', ['override', 'score', 'applied'])
def test_cloud_upsert_preserves_existing_protection(db, protection):
    row = observation('Principal Engineer' if protection == 'override' else 'Frontend Engineer')
    [pid] = write(db, row)['inserted_posting_ids']
    if protection == 'override':
        db.execute("update postings set relevance_gate=relevance_gate || '{\"override\":true}'::jsonb where id=%s", (pid,))
    elif protection == 'applied':
        db.execute("select set_status(%s,'applied')", (pid,))
    else:
        payload = dict(employer_type='direct', seniority_real=None, fit_score=72, fit_tier='good',
                       recommendation='apply', reasons=[], fit_line='', fit_line_evidence_ids=[], luna_status='ok')
        labels = dict(role_type=None, seniority_match='unknown', remote_ok='unknown', red_flag_count=0)
        db.execute("insert into posting_scores(posting_id,score,brain,model,scorer_version,posting_sha256,profile_sha256,history_sha256,score_payload,labels) values(%s,72,'synthetic','synthetic','1',%s,%s,%s,%s::jsonb,%s::jsonb)",
                   (pid, *(['a' * 64] * 3), json.dumps(payload), json.dumps(labels)))
    write(db, {**row, 'title': 'Principal Engineer'})
    assert db.execute('select relevance_filtered from postings where id=%s', (pid,)).fetchone() == (False,)


def test_cloud_gate_failure_rolls_back_posting_and_status(db, monkeypatch):
    from scraper import relevance
    def fail(*args, **kwargs):
        raise RuntimeError('synthetic gate failure')
    monkeypatch.setattr(relevance, 'refresh_gate', fail)
    with pytest.raises(RuntimeError, match='synthetic gate failure'):
        write(db, observation())
    assert db.execute('select count(*) from postings').fetchone() == (0,)
    assert db.execute('select count(*) from posting_status').fetchone() == (0,)


def test_cloud_gate_covers_entire_batch_and_empty_harvest_does_not_scan_backlog(db):
    rows = [{**observation(), 'id': f'cloud-{index}'} for index in range(1001)]
    assert len(persist_postings_with_disposition(db, rows, '2026-10-11T06:00:00Z')['inserted_posting_ids']) == 1001
    assert db.execute('select count(*) from postings where relevance_filtered').fetchone() == (1001,)
    db.execute("update postings set relevance_gate='{}'::jsonb")
    assert persist_postings_with_disposition(db, [], '2026-10-11T06:00:00Z')['observed_posting_ids'] == []
    assert db.execute('select count(*) from postings where relevance_filtered').fetchone() == (0,)


@pytest.mark.parametrize('status', ['new', 'seen'])
@pytest.mark.parametrize('title,jd,rule', [
    pytest.param('Principal Engineer', 'Build React and TypeScript products. ' * 20, 'leadership-title-strict', id='leadership'),
    pytest.param('Frontend Engineer', 'Applicants must already live in the US. ' * 20, 'already-us-resident', id='residency'),
])
def test_backfill_commits_gate_before_board_and_poll_reads(db, status, title, jd, rule):
    row = {**observation(title, None), 'source': 'lever',
           'url': 'https://jobs.lever.co/synthetic/cloud-gate'}
    [pid] = write(db, row)['inserted_posting_ids']
    db.execute('select set_status(%s,%s)', (pid, status))
    assert backfill(db, fetcher=lambda _: jd)['stored'] == 1
    assert db.execute('select raw_jd,relevance_filtered,relevance_gate from postings where id=%s',
                      (pid,)).fetchone() == (jd, True, dict(version=VERSION, rule=rule))
    for view in ['all', 'new-for-me', 'seen', 'not-scored']:
        assert bool(db.execute('select id from board_postings(filter=>%s)', (view,)).fetchall()) == (view == 'not-scored')
        snapshot = db.execute("select get_new_roles_snapshot(%s,'active','2026-10-11T05:00:00Z')", (view,)).fetchone()[0]
        assert bool(snapshot['incoming']) == (view == 'not-scored')


@pytest.mark.parametrize('change', ['title', 'jd_text', 'both'])
def test_text_changing_upsert_preserves_score_anyway(db, change):
    row = observation()
    [pid] = write(db, row)['inserted_posting_ids']
    assert db.execute('select score_anyway(%s)', (pid,)).fetchone() == (True,)
    changed = {**row}
    if change in ('title', 'both'):
        changed['title'] = 'Staff Engineer'
    if change in ('jd_text', 'both'):
        changed['jd_text'] += ' More role details.'
    write(db, changed)
    filtered, gate = db.execute('select relevance_filtered,relevance_gate from postings where id=%s', (pid,)).fetchone()
    assert filtered is False and gate == dict(override=True, score_requested=True)


def test_backfill_preserves_score_anyway(db):
    row = {**observation(jd=None), 'source': 'lever',
           'url': 'https://jobs.lever.co/synthetic/cloud-gate'}
    [pid] = write(db, row)['inserted_posting_ids']
    db.execute('select score_anyway(%s)', (pid,))
    backfill(db, fetcher=lambda _: 'Build React and TypeScript products. ' * 20)
    assert db.execute('select relevance_filtered,relevance_gate from postings where id=%s',
                      (pid,)).fetchone() == (False, dict(override=True, score_requested=True))


def test_backfill_gate_failure_rolls_back_description_and_fetch_metadata(db, monkeypatch):
    from scraper import relevance
    row = {**observation(jd=None), 'source': 'lever',
           'url': 'https://jobs.lever.co/synthetic/cloud-gate'}
    [pid] = write(db, row)['inserted_posting_ids']
    before = db.execute('select raw_jd,liveness,relevance_gate from postings where id=%s', (pid,)).fetchone()
    def fail(*args, **kwargs):
        raise RuntimeError('synthetic gate failure')
    monkeypatch.setattr(relevance, 'refresh_gate', fail)
    with pytest.raises(RuntimeError, match='synthetic gate failure'):
        backfill(db, fetcher=lambda _: 'Build React and TypeScript products. ' * 20)
    assert db.execute('select raw_jd,liveness,relevance_gate from postings where id=%s', (pid,)).fetchone() == before


def test_text_invalidation_preserves_false_owner_keys_and_refresh_keeps_request(db):
    from scraper.relevance import refresh_gate
    [pid] = write(db, observation())['inserted_posting_ids']
    db.execute("update postings set relevance_gate=relevance_gate || %s::jsonb where id=%s",
               (json.dumps(dict(override=False, score_requested=True, synthetic_computed='stale')), pid))
    db.execute("update postings set title='Frontend Engineer' where id=%s", (pid,))
    assert db.execute('select relevance_gate from postings where id=%s', (pid,)).fetchone() == (dict(override=False, score_requested=True),)
    refresh_gate(db, posting_ids=[pid], at_write=True)
    assert db.execute('select relevance_gate from postings where id=%s', (pid,)).fetchone() == (dict(override=False, score_requested=True, version=VERSION, rule=None),)
