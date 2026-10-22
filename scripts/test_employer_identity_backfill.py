"""Offline planning/receipt tests; the SQL contract can also run on disposable PG."""
from contextlib import nullcontext
from copy import deepcopy
import hashlib
import json
import os
from uuid import UUID

import pytest

from scraper.employer_identity import VERSION
from scripts.employer_identity_backfill import backfill_connection, plan_identity


def row(number=1, version=None, **changes):
    jd = 'Monday.com is hiring engineers.'
    facts = {'stack': [{'value': 'Python'}]}
    if version is not None:
        facts['employer_identity'] = {'resolver_version': version, 'hiring_employer': None}
    return dict(id=UUID(int=number), company='EngRadar', source='linkedin', raw_jd=jd,
                jd_sha256=hashlib.sha256(jd.encode()).hexdigest(), facts=facts, **changes)


@pytest.mark.parametrize('version', [None, '1', str(int(VERSION) - 1)])
def test_missing_or_older_identity_is_planned_without_changing_input(version):
    original = row(version=version)
    before = deepcopy(original)
    assert plan_identity(original)['hiring_employer'] == 'Monday.com'
    assert original == before


@pytest.mark.parametrize('version', [VERSION, str(int(VERSION) + 1), 'unknown', ''])
def test_current_future_or_unrecognized_versions_are_not_downgraded(version):
    assert plan_identity(row(version=version)) is None


@pytest.mark.parametrize('change', [{'raw_jd': 'Changed JD'}, {'raw_jd': None}, {'jd_sha256': '0' * 64}])
def test_stale_or_missing_posting_text_is_not_backfilled(change):
    original = row()
    original.update(change)
    assert plan_identity(original) is None


class Connection:
    def __init__(self, rows, raced=False):
        self.rows, self.raced, self.writes, self.batch_sizes = deepcopy(rows), raced, [], []
        self.rowcount = 0

    def transaction(self):
        return nullcontext()

    def execute(self, query, params=()):
        if query.lstrip().lower().startswith('select'):
            self.selected = [r for r in self.rows if r['id'] > params[0]][:params[2]]
            self.batch_sizes.append(len(self.selected))
        elif query.lstrip().lower().startswith('update'):
            self.writes.append((query, params))
            self.rowcount = 0 if self.raced else 1
            if not self.raced:
                identity, posting_id, *_ = params
                target = next(r for r in self.rows if r['id'] == posting_id)
                target['facts']['employer_identity'] = json.loads(identity)
        else:
            assert query.lower() == 'set transaction read only'
        return self

    def fetchall(self):
        return self.selected


def test_default_dry_run_batches_and_samples_without_writes():
    connection = Connection([row(i) for i in range(1, 6)])
    receipt = backfill_connection(connection, batch_size=2)
    assert receipt['planned'] == 5 and receipt['applied'] == 0
    assert receipt['examples'][0]['after'] == 'Monday.com via EngRadar'
    assert receipt['examples'][0]['before'] == 'EngRadar (agency — client undisclosed)'
    assert connection.writes == []
    assert connection.batch_sizes == [2, 2, 1, 0]


def test_apply_preserves_other_facts_and_is_idempotent():
    connection = Connection([row(), row(2, VERSION), row(3, str(int(VERSION) + 1))])
    receipt = backfill_connection(connection, apply=True, batch_size=2)
    assert receipt['planned'] == receipt['applied'] == 1
    assert connection.rows[0]['facts']['stack'] == [{'value': 'Python'}]
    assert backfill_connection(connection, apply=True)['applied'] == 0
    query, _ = connection.writes[0]
    assert "jsonb_set(e.facts, '{employer_identity}'" in query
    assert "resolver_version' is not distinct from" in query
    assert 'e.jd_sha256 = %s' in query and 'p.raw_jd = %s' in query


def test_raced_update_is_reported_as_skipped():
    receipt = backfill_connection(Connection([row()], raced=True), apply=True)
    assert receipt['applied'] == 0 and receipt['skipped_race'] == 1


@pytest.mark.parametrize('arguments,applied', [([], 0), (['--dry-run'], 0), (['--apply'], 1)])
def test_cli_defaults_to_dry_run(monkeypatch, capsys, arguments, applied):
    from scripts import employer_identity_backfill as module
    connection = Connection([row()])
    monkeypatch.setenv('DATABASE_URL', 'postgresql://localhost/offline-test')
    monkeypatch.setattr(module.psycopg, 'connect', lambda *args, **kwargs: nullcontext(connection))
    assert module.main(arguments) == 0
    assert json.loads(capsys.readouterr().out)['applied'] == applied


@pytest.mark.parametrize('batch_size', [0, 1001])
def test_invalid_batch_size_is_rejected_before_query(batch_size):
    with pytest.raises(ValueError, match='batch_size'):
        backfill_connection(Connection([]), batch_size=batch_size)


@pytest.mark.skipif(not os.environ.get('DATABASE_URL'), reason='explicit disposable PG URL required')
def test_sql_on_disposable_postgres():
    import psycopg
    from psycopg.rows import dict_row
    from test_support.postgres import migrated_database
    from pathlib import Path
    # The harness creates/removes a sibling database, never the supplied database.
    from scripts.backfill_posting_facts import require_local_database_url
    url = os.environ['DATABASE_URL']
    require_local_database_url(url)
    previous = os.environ.get('DATABASE_URL')
    os.environ['DATABASE_URL'] = url
    try:
        with migrated_database(Path(__file__).parents[1] / 'supabase/migrations', through=28) as disposable:
            with psycopg.connect(disposable, row_factory=dict_row) as db:
                from extractor.test_persistence import RAW_JD
                original = row()
                original['raw_jd'] += '\n' + RAW_JD
                db.execute("insert into postings(id,source,external_id,url,title,company,raw_jd) values (%s,'linkedin','p7b','https://example.test','Engineer','EngRadar',%s)", (original['id'], original['raw_jd']))
                from extractor.test_persistence import extraction
                from extractor.persistence import persist_extraction
                # Persistence expects tuple rows, while the backfill follows dict-row scripts.
                from psycopg.rows import tuple_row
                db.row_factory = tuple_row
                persist_extraction(db, str(original['id']), original['raw_jd'], extraction(raw_jd=original['raw_jd']))
                db.row_factory = dict_row
                db.execute("update posting_extractions set facts=facts-'employer_identity'")
                db.commit()
                before = db.execute('select to_jsonb(e) value from posting_extractions e').fetchone()['value']
                db.commit()
                assert backfill_connection(db)['planned'] == 1
                assert backfill_connection(db, apply=True)['applied'] == 1
                after = db.execute('select to_jsonb(e) value from posting_extractions e').fetchone()['value']
                assert after['facts'].pop('employer_identity')['hiring_employer'] == 'Monday.com'
                assert after == before
                db.commit()
                assert backfill_connection(db, apply=True)['applied'] == 0
    finally:
        if previous is None:
            os.environ.pop('DATABASE_URL', None)
        else:
            os.environ['DATABASE_URL'] = previous
