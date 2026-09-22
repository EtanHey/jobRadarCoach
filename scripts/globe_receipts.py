"""Serialized mutations with immutable receipts and committed database ownership."""
import hashlib
import json
import os
import re
import subprocess
from contextlib import contextmanager
from pathlib import Path
from uuid import UUID, uuid4

from psycopg import sql
from psycopg.pq import TransactionStatus

from scripts.geocode_locations import single_process

TABLES = {'posting_geo': ('posting_id', 'lat', 'lng', 'precision', 'source', 'resolved_at'),
          'company_hq': ('company', 'lat', 'lng', 'city', 'country', 'source', 'resolved_at')}
MUTATION_LOCK = 74201922


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


@contextmanager
def mutation(db):
    # Own the whole transaction: never commit callers' unrelated pending writes.
    if db.info.transaction_status != TransactionStatus.IDLE:
        raise ValueError('Geography mutation requires an idle connection')
    with single_process(), db.transaction():
        if not db.execute('select pg_try_advisory_xact_lock(%s) locked', (MUTATION_LOCK,)).fetchone()['locked']:
            raise RuntimeError('Another geography mutation holds the database lock')
        yield


def target_id(db):
    target = db.execute('select target_id::text from public.globe_geo_target where singleton and database_oid=(select oid from pg_catalog.pg_database where datname=current_database())').fetchone()
    if not target:
        raise ValueError('Target identity missing or cloned database requires operator reprovisioning')
    return target['target_id']


@contextmanager
def reserve_receipt(path):
    # Exclusive create rejects existing paths, symlinks and concurrent reservations.
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'wb') as file:
        os.fsync(file.fileno())
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        yield file


def publish_receipt(file, receipt):
    file.write(encoded(receipt) + b'\n')
    file.flush()
    os.fchmod(file.fileno(), 0o400)
    os.fsync(file.fileno())


def source_identity():
    root = Path(__file__).resolve().parents[1]
    head = subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'], text=True).strip()
    paths = ['scripts/globe_receipts.py', 'scripts/globe_geocode.py', 'scripts/geocode_locations.py',
             'supabase/migrations/0017_globe_apply_identity.sql']
    return head, hashlib.sha256(b''.join((root / p).read_bytes() for p in paths)).hexdigest()


def apply_owned(db, plan, path, insert):
    head, tool_hash = source_identity()
    with mutation(db):
        target = target_id(db)
        with reserve_receipt(path) as file:
            receipt = {'version': 1, 'target_id': target, 'apply_id': str(uuid4()),
                       'plan_sha256': hashlib.sha256(encoded(plan)).hexdigest(),
                       'source_head': head, 'tool_sha256': tool_hash}
            db.execute('insert into public.globe_geo_applies(apply_id,target_id) values (%s,%s)', (receipt['apply_id'], target))
            receipt['rows'] = insert(db, plan, receipt['apply_id'])
            validate_receipt(receipt)
            db.execute('update public.globe_geo_applies set receipt=%s::jsonb where apply_id=%s',
                       (encoded(receipt).decode(), receipt['apply_id']))
            # File alone is not a commit claim: rollback requires its committed journal twin.
            publish_receipt(file, receipt)
    return {table: len(rows) for table, rows in receipt['rows'].items()}


def require(condition):
    if not condition:
        raise ValueError('Invalid receipt field')


def validate_receipt(receipt):
    keys = {'version', 'target_id', 'apply_id', 'plan_sha256', 'source_head', 'tool_sha256', 'rows'}
    try:
        require(isinstance(receipt, dict) and set(receipt) == keys)
        require(type(receipt['version']) is int and receipt['version'] == 1)
        for field in ('target_id', 'apply_id'):
            require(isinstance(receipt[field], str) and str(UUID(receipt[field])) == receipt[field])
        for field, size in (('plan_sha256', 64), ('source_head', 40), ('tool_sha256', 64)):
            require(isinstance(receipt[field], str) and re.fullmatch('[a-f0-9]{%d}' % size, receipt[field]))
        require(isinstance(receipt['rows'], dict) and set(receipt['rows']) == set(TABLES))
        for table, columns in TABLES.items():
            rows = receipt['rows'][table]
            require(isinstance(rows, list))
            seen = set()
            for row in rows:
                require(isinstance(row, dict) and set(row) == set(columns) | {'geo_apply_id'})
                require(row['geo_apply_id'] == receipt['apply_id'])
                require(isinstance(row[columns[0]], str) and row[columns[0]] not in seen)
                seen.add(row[columns[0]])
        encoded(receipt)
    except (AssertionError, ValueError, TypeError, KeyError, AttributeError):
        raise ValueError('Malformed or unsupported geography receipt') from None


def rollback_owned(db, receipt):
    validate_receipt(receipt)  # Entire envelope validated before the first database mutation.
    with mutation(db):
        if target_id(db) != receipt['target_id']:
            raise ValueError('Receipt belongs to another target')
        ledger = db.execute('select receipt from public.globe_geo_applies where apply_id=%s and target_id=%s for update',
                            (receipt['apply_id'], receipt['target_id'])).fetchone()
        if ledger is None or encoded(ledger['receipt']) != encoded(receipt):
            raise ValueError('Receipt does not match a committed apply on this target')
        counts = {}
        for table, columns in TABLES.items():
            counts[table] = 0
            for row in receipt['rows'][table]:
                result = db.execute(sql.SQL('delete from public.{} t where t.{}=%s and t.geo_apply_id=%s and to_jsonb(t)=%s::jsonb').format(
                    sql.Identifier(table), sql.Identifier(columns[0])),
                    (row[columns[0]], receipt['apply_id'], encoded(row).decode()))
                counts[table] += result.rowcount
    return counts
