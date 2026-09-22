"""Prepare a real-data geography plan; only explicit apply/rollback commands mutate DB."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from scripts.geocode_locations import ENDPOINT, Geocoder, atomic_json, prepare, single_process

from scripts.globe_receipts import TABLES, apply_owned, rollback_owned


def snapshot(db):
    db.execute('set transaction read only')
    return db.execute('select id::text, company, location, remote from public.postings order by id').fetchall()


def apply_plan(db, plan, receipt_path):
    return apply_owned(db, plan, receipt_path, _insert_plan)


def _insert_plan(db, plan, apply_id):
    # Fail on stale snapshots; a coordinate for an old location must never follow a changed posting.
    expected = {p['id']: p for p in plan['postings']}
    current = db.execute('select id::text, company, location, remote from public.postings where id = any(%s::uuid[]) for share', (list(expected),)).fetchall()
    if {p['id']: p for p in current} != expected:
        raise ValueError('Posting snapshot changed; take a fresh snapshot and prepare again using cache')
    receipt = {table: [] for table in TABLES}
    for table, columns in TABLES.items():
        columns = (*columns, 'geo_apply_id')
        for raw_row in plan[table]:
            row = {**raw_row, 'geo_apply_id': apply_id}
            if table == 'posting_geo' and row['posting_id'] not in expected:
                raise ValueError('Geography references a posting outside the snapshot')
            if table == 'company_hq' and row['company'] not in {p['company'] for p in expected.values()}:
                raise ValueError('HQ references a company outside the snapshot')
            query = sql.SQL('insert into public.{} ({}) values ({}) on conflict do nothing returning to_jsonb({}.*) as row').format(
                sql.Identifier(table), sql.SQL(',').join(map(sql.Identifier, columns)),
                sql.SQL(',').join(sql.Placeholder() for _ in columns), sql.Identifier(table))
            inserted = db.execute(query, [row[c] for c in columns]).fetchone()
            if inserted:
                receipt[table].append(inserted['row'])
    return receipt


def rollback_plan(db, receipt):
    return rollback_owned(db, receipt)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_subparsers(dest='mode', required=True)
    snap = modes.add_parser('snapshot', help='Read-only DATABASE_URL snapshot; credentials never written')
    snap.add_argument('--out', required=True, type=Path)
    prep = modes.add_parser('prepare', help='No database writes; cached, single-process geocoding')
    prep.add_argument('--snapshot', required=True, type=Path)
    prep.add_argument('--cache', required=True, type=Path)
    prep.add_argument('--out', required=True, type=Path)
    prep.add_argument('--hq-evidence', type=Path)
    prep.add_argument('--exclude-queries', type=Path, help='Reviewed ambiguous posting queries to keep unresolved')
    prep.add_argument('--endpoint', default=ENDPOINT)
    prep.add_argument('--one-time', action='store_true', help='Small one-off run at <=1 request/s; otherwise <=4/min')
    apply = modes.add_parser('apply', help='OPERATOR ONLY: inserts missing rows, preserves existing coordinates')
    apply.add_argument('--plan', required=True, type=Path)
    apply.add_argument('--receipt', required=True, type=Path)
    rollback = modes.add_parser('rollback', help='OPERATOR ONLY: removes unchanged rows listed in apply receipt')
    rollback.add_argument('--receipt', required=True, type=Path)
    args = parser.parse_args()
    if args.mode == 'prepare':
        with single_process():
            g = Geocoder(args.cache, endpoint=args.endpoint, one_time=args.one_time)
            postings = json.loads(args.snapshot.read_text())
            exclusions = json.loads(args.exclude_queries.read_text()) if args.exclude_queries else []
            plan = prepare(postings, g, json.loads(args.hq_evidence.read_text()) if args.hq_evidence else [], exclusions)
            plan['excluded_queries'] = exclusions
            plan['postings'] = postings
            atomic_json(args.out, plan)
            print(json.dumps({'counts': plan['counts'], 'network_requests': g.requests}))
        return
    with psycopg.connect(os.environ['DATABASE_URL'], row_factory=dict_row) as db:
        if args.mode == 'snapshot':
            rows = snapshot(db)
            atomic_json(args.out, rows)
            print(json.dumps({'postings': len(rows)}))
        elif args.mode == 'apply':
            print(json.dumps(apply_plan(db, json.loads(args.plan.read_text()), args.receipt)))
        else:
            print(json.dumps(rollback_plan(db, json.loads(args.receipt.read_text()))))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        # DB/HTTP exception messages can contain credentials or connection strings.
        raise SystemExit(f'Geocoding stopped ({type(error).__name__}); cache retained, no partial database transaction committed.') from None
