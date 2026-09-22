"""Adversarial receipt probes. Targets are disposable local databases only."""
import json
from pathlib import Path
from threading import Event, Thread

import psycopg
import pytest
from psycopg.rows import dict_row

from scripts.globe_geocode import apply_plan, rollback_plan
from test_support.postgres import migrated_database
from test_support.test_job_api import _seed, IDS

MIGRATIONS = Path(__file__).parents[1] / 'supabase/migrations'


def plan_for(db, ids=IDS[:1]):
    postings = db.execute('select id::text, company, location, remote from postings').fetchall()
    db.commit()
    row = {'lat': 32, 'lng': 34, 'precision': 'city', 'source': 'fixture', 'resolved_at': '2026-09-22T00:00:00Z'}
    return {'postings': postings, 'posting_geo': [row | {'posting_id': id} for id in ids], 'company_hq': []}


def test_wrong_target_identical_preexisting_row_is_never_deleted(tmp_path):
    with migrated_database(MIGRATIONS, through=17) as a, migrated_database(MIGRATIONS, through=17) as b:
        with psycopg.connect(a, row_factory=dict_row) as db_a, psycopg.connect(b, row_factory=dict_row) as db_b:
            _seed(db_a); _seed(db_b)
            plan = plan_for(db_a)
            path = tmp_path / 'a.json'
            apply_plan(db_a, plan, path); db_a.commit()
            db_b.execute("insert into posting_geo(posting_id,lat,lng,precision,source,resolved_at) values (%s,32,34,'city','fixture','2026-09-22T00:00:00Z')", (IDS[0],)); db_b.commit()
            with pytest.raises(ValueError):
                rollback_plan(db_b, json.loads(path.read_text()))
            db_b.rollback()
            assert db_b.execute('select count(*) n from posting_geo').fetchone()['n'] == 1


def test_concurrent_apply_cannot_replace_reserved_receipt(tmp_path, monkeypatch):
    import scripts.globe_receipts as module
    entered, release = Event(), Event()
    original = module.publish_receipt
    def blocked(path, value):
        if not entered.is_set():
            entered.set()
            assert release.wait(5)
        original(path, value)
    monkeypatch.setattr(module, 'publish_receipt', blocked)
    with migrated_database(MIGRATIONS, through=17) as url:
        with psycopg.connect(url, row_factory=dict_row) as db:
            _seed(db)
            first, second = plan_for(db), plan_for(db, IDS[1:2])
        errors = []
        def apply_first():
            try:
                with psycopg.connect(url, row_factory=dict_row) as db:
                    apply_plan(db, first, tmp_path / 'shared.json')
            except Exception as error:
                errors.append(error)
        thread = Thread(target=apply_first); thread.start()
        assert entered.wait(5)
        try:
            with psycopg.connect(url, row_factory=dict_row) as db:
                with pytest.raises((ValueError, RuntimeError, FileExistsError)):
                    apply_plan(db, second, tmp_path / 'shared.json')
        finally:
            release.set(); thread.join(5)
        assert not errors
        saved = (tmp_path / 'shared.json').read_bytes()
        with psycopg.connect(url, row_factory=dict_row) as db:
            assert db.execute('select count(*) n from posting_geo').fetchone()['n'] == 1
            db.commit()
            with pytest.raises(FileExistsError):
                apply_plan(db, second, tmp_path / 'shared.json')
        assert (tmp_path / 'shared.json').read_bytes() == saved


def test_malformed_forged_and_reinserted_rows_fail_closed(tmp_path):
    import copy
    with migrated_database(MIGRATIONS, through=17) as url:
        with psycopg.connect(url, row_factory=dict_row) as db:
            _seed(db)
            plan = plan_for(db, IDS[:2])
            path = tmp_path / 'receipt.json'
            apply_plan(db, plan, path)
            receipt = json.loads(path.read_text())
            variants = [{}, {'posting_geo': [], 'company_hq': []}, receipt | {'version': True},
                        receipt | {'target_id': 'not-a-uuid'}, receipt | {'plan_sha256': '0' * 64},
                        receipt | {'rows': {'posting_geo': [], 'company_hq': 'bad'}}]
            broken = copy.deepcopy(receipt); broken['rows']['posting_geo'][1]['geo_apply_id'] = 'guess'
            variants.append(broken)
            forged = copy.deepcopy(receipt); forged['apply_id'] = '00000000-0000-0000-0000-000000000001'
            for row in forged['rows']['posting_geo']:
                row['geo_apply_id'] = forged['apply_id']
            variants.append(forged)
            for bad in variants:
                with pytest.raises(ValueError):
                    rollback_plan(db, bad)
                assert db.execute('select count(*) n from posting_geo').fetchone()['n'] == 2
                db.commit()
            db.execute('delete from posting_geo where posting_id=%s', (IDS[0],))
            db.execute("insert into posting_geo(posting_id,lat,lng,precision,source,resolved_at) values (%s,32,34,'city','fixture','2026-09-22T00:00:00Z')", (IDS[0],))
            db.commit()
            assert rollback_plan(db, receipt) == {'posting_geo': 1, 'company_hq': 0}
            assert db.execute('select geo_apply_id from posting_geo').fetchone()['geo_apply_id'] is None


def test_database_lock_serializes_other_clients_and_apply_rollback(tmp_path):
    from scripts.globe_receipts import MUTATION_LOCK
    from scripts.geocode_locations import single_process
    with migrated_database(MIGRATIONS, through=17) as url:
        with psycopg.connect(url, row_factory=dict_row) as db, psycopg.connect(url) as other:
            _seed(db)
            plan = plan_for(db); path = tmp_path / 'ok.json'
            apply_plan(db, plan, path)
            with single_process():
                with pytest.raises(RuntimeError):
                    rollback_plan(db, json.loads(path.read_text()))
            other.execute('select pg_advisory_xact_lock(%s)', (MUTATION_LOCK,))
            for action in (lambda: apply_plan(db, plan, tmp_path / 'blocked.json'), lambda: rollback_plan(db, json.loads(path.read_text()))):
                with pytest.raises(RuntimeError, match='database lock'):
                    action()
            assert not (tmp_path / 'blocked.json').exists()
            other.rollback()
            assert rollback_plan(db, json.loads(path.read_text()))['posting_geo'] == 1


def test_receipt_written_but_transaction_failed_is_not_rollback_authority(tmp_path, monkeypatch):
    import scripts.globe_receipts as module
    original = module.publish_receipt
    def fail(file, receipt):
        original(file, receipt)
        raise OSError('simulated crash before commit')
    monkeypatch.setattr(module, 'publish_receipt', fail)
    with migrated_database(MIGRATIONS, through=17) as url:
        with psycopg.connect(url, row_factory=dict_row) as db:
            _seed(db)
            plan = plan_for(db); path = tmp_path / 'orphan.json'
            with pytest.raises(OSError):
                apply_plan(db, plan, path)
            assert db.execute('select count(*) n from globe_geo_applies').fetchone()['n'] == 0
            assert db.execute('select count(*) n from posting_geo').fetchone()['n'] == 0
            db.commit()
            with pytest.raises(ValueError, match='committed apply'):
                rollback_plan(db, json.loads(path.read_text()))


def test_exclusive_reservation_refuses_collisions_and_symlinks(tmp_path):
    from scripts.globe_receipts import reserve_receipt
    path = tmp_path / 'exclusive.json'
    with reserve_receipt(path):
        with pytest.raises(FileExistsError):
            with reserve_receipt(path):
                pytest.fail('reused active reservation')
    link = tmp_path / 'link.json'; link.symlink_to(path)
    with pytest.raises(FileExistsError):
        with reserve_receipt(link):
            pytest.fail('followed symlink')
    assert path.read_bytes() == b''
