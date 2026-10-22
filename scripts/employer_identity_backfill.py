"""Deterministic employer identity backfill; dry-run by default, no model calls.

Usage: python -m scripts.employer_identity_backfill --dry-run
Uses DATABASE_URL, like other backfill scripts. --apply commits bounded batches.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scraper.employer_aliases import is_alias
from scraper.employer_identity import PUBLISHER_KEYS, VERSION, resolve_employer


SELECT_BATCH = """select p.id, p.company, p.source, p.raw_jd, e.jd_sha256, e.facts
    from public.postings p join public.posting_extractions e on e.posting_id = p.id
    where p.id > %s and
      case when e.facts->'employer_identity'->>'resolver_version' ~ '^[0-9]{1,9}$'
        then (e.facts->'employer_identity'->>'resolver_version')::int < %s::int
        else e.facts->'employer_identity'->>'resolver_version' is null end
      and e.jd_sha256 = encode(sha256(convert_to(p.raw_jd, 'UTF8')), 'hex')
    order by p.id limit %s"""
UPDATE_IDENTITY = """update public.posting_extractions e
    set facts = jsonb_set(e.facts, '{employer_identity}', %s::jsonb, true)
    from public.postings p where e.posting_id = p.id and p.id = %s
      and e.facts->'employer_identity'->>'resolver_version' is not distinct from %s
      and e.jd_sha256 = %s and p.raw_jd = %s and p.company = %s and p.source = %s"""


def plan_identity(row):
    identity = row['facts'].get('employer_identity')
    version = identity.get('resolver_version') if isinstance(identity, dict) else None
    if version is not None and (not isinstance(version, str) or not version.isascii()
                                or not version.isdecimal() or len(version) > 9
                                or int(version) >= int(VERSION)):
        return None
    text = row['raw_jd']
    if not isinstance(text, str) or hashlib.sha256(text.encode()).hexdigest() != row['jd_sha256']:
        return None
    return resolve_employer(row['company'], text, row['source'])


def _label(publisher, identity):
    """Report the same catalog/evidence/alias labels as the dashboard."""
    if not isinstance(identity, dict) or identity.get('publisher') != publisher:
        identity = {}
    employer = identity.get('hiring_employer')
    if employer:
        return (publisher if employer.casefold() == publisher.casefold() or is_alias(publisher, employer)
                else f'{employer} via {publisher}')
    agency = publisher.casefold() in PUBLISHER_KEYS or identity.get('agency_evidence')
    return f'{publisher} (agency — client undisclosed)' if agency else publisher


def backfill_connection(connection, *, apply=False, batch_size=100):
    if not 1 <= batch_size <= 1000:
        raise ValueError('batch_size must be between 1 and 1000')
    receipt = dict(resolver_version=VERSION, dry_run=not apply, scanned=0, planned=0,
                   applied=0, skipped_race=0, examples=[])
    last_id = UUID(int=0)
    while True:
        with connection.transaction():
            if not apply:
                connection.execute('set transaction read only')
            # Lock postings before rewriting extraction facts, as persistence does.
            # This also prevents JD/company/source changes during this batch.
            query = SELECT_BATCH + (' for update of p, e' if apply else '')
            rows = connection.execute(query, (last_id, VERSION, batch_size)).fetchall()
            for row in rows:
                receipt['scanned'] += 1
                identity = plan_identity(row)
                if identity is None:
                    continue
                before = row['facts'].get('employer_identity')
                receipt['planned'] += 1
                if len(receipt['examples']) < 20:
                    receipt['examples'].append(dict(id=str(row['id']),
                        before=_label(row['company'], before), after=_label(row['company'], identity)))
                if apply:
                    result = connection.execute(UPDATE_IDENTITY, (
                        json.dumps(identity, ensure_ascii=False), row['id'],
                        before.get('resolver_version') if isinstance(before, dict) else None,
                        row['jd_sha256'], row['raw_jd'], row['company'], row['source'],
                    ))
                    receipt['applied'] += result.rowcount
                    receipt['skipped_race'] += 1 - result.rowcount
        if not rows:
            break
        last_id = rows[-1]['id']
    return receipt


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--dry-run', action='store_true', help='Read only (default)')
    mode.add_argument('--apply', action='store_true', help='Write only facts.employer_identity')
    parser.add_argument('--batch-size', type=int, default=100)
    args = parser.parse_args(argv)
    if not 1 <= args.batch_size <= 1000:
        parser.error('batch_size must be between 1 and 1000')
    try:
        with psycopg.connect(os.environ['DATABASE_URL'], row_factory=dict_row) as connection:
            receipt = backfill_connection(connection, apply=args.apply, batch_size=args.batch_size)
    except (KeyError, psycopg.Error):
        # Do not echo a connection string or server error containing credentials.
        print('Backfill database unavailable; check DATABASE_URL and database access.', file=sys.stderr)
        return 2
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
