"""Backfill current-profile score eligibility locally, without model calls.

Run from the checkout: python -m scripts.eligibility_backfill [--dry-run|--apply]
Uses DATABASE_URL. Apply requires migration 0037 and the eligibility-aware UI.
Use --recompute-unknown to revisit only stored unknown decisions.
Each batch commits separately; rerunning safely resumes after an interruption.
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
import os
from pathlib import Path
import sys
from uuid import UUID

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from classifier.persistence import _sha256
from classifier.projection import profile_contract
from scraper.eligibility import decide_location_eligibility


UPDATE = """
update public.posting_scores
set score_payload = score_payload || %s::jsonb
where posting_id = %s and profile_sha256 = %s
  and not (score_payload ? 'eligibility')
"""


RECOMPUTE_UPDATE = """
update public.posting_scores
set score_payload = score_payload || %s::jsonb
where posting_id = %s and profile_sha256 = %s
  and score_payload->>'eligibility' = 'unknown'
  and (score_payload->'eligibility', score_payload->'eligibility_reason')
      is distinct from (%s::jsonb, %s::jsonb)
"""


def plan_rows(rows, profile, profile_sha256, *, recompute_unknown=False):
    """Use the scorer's projected profile, original posting and extraction."""
    for row in rows:
        payload = row['score_payload']
        selected = (payload.get('eligibility') == 'unknown' if recompute_unknown
                    else 'eligibility' not in payload)
        if row['profile_sha256'] != profile_sha256 or not selected:
            continue
        decision = decide_location_eligibility(row, row.get('posting_extractions'), profile)
        if recompute_unknown and all(payload.get(key) == value for key, value in decision.items()):
            continue
        yield row, decision


def apply_rows(connection, planned, profile_sha256, *, recompute_unknown=False):
    applied = 0
    for row, decision in planned:
        patch = {key: decision[key] for key in ('eligibility', 'eligibility_reason')}
        params = (Jsonb(patch), row['id'], profile_sha256)
        if recompute_unknown:
            params += (Jsonb(patch['eligibility']), Jsonb(patch['eligibility_reason']))
        applied += connection.execute(
            RECOMPUTE_UPDATE if recompute_unknown else UPDATE, params
        ).rowcount
    return applied


def backfill_connection(connection, *, apply=False, batch_size=100, recompute_unknown=False):
    """Read and optionally merge batches on an idle/autocommit connection."""
    if type(batch_size) is not int or not 1 <= batch_size <= 1000:
        raise ValueError('batch_size must be between 1 and 1000')
    counts = Counter(eligible=0, blocked=0, unknown=0)
    samples = []
    applied = planned_count = batches = 0
    last_id = UUID(int=0)
    initial_profile_sha256 = None
    while True:
        with connection.transaction():
            if apply:
                # Keep profile/extraction writes out of this short batch, including
                # inserts for postings with no extraction yet. Posting and score
                # rows are locked below. No model is invoked under these locks.
                connection.execute("set local lock_timeout = '5s'")
                connection.execute(
                    'lock table public.profile, public.posting_extractions in share mode'
                )
            else:
                connection.execute('set transaction isolation level repeatable read read only')
            with connection.cursor(row_factory=dict_row) as cursor:
                snapshot = {row['field']: row['value'] for row in cursor.execute(
                    'select field, value from public.profile order by field'
                ).fetchall()}
                profile = profile_contract(snapshot)
                profile_sha256 = _sha256(profile)
                if initial_profile_sha256 is None:
                    initial_profile_sha256 = profile_sha256
                elif profile_sha256 != initial_profile_sha256:
                    raise ValueError('Profile changed during backfill; rerun for the current profile')
                selection = ("s.score_payload->>'eligibility' = 'unknown'" if recompute_unknown
                             else "not (s.score_payload ? 'eligibility')")
                rows = cursor.execute(
                    f"""select p.id, p.title, p.company, p.location, p.raw_jd,
                              p.remote, to_jsonb(p)->>'work_mode' as work_mode,
                              case when e.posting_id is null then null
                                   else jsonb_build_object('facts', e.facts) end as posting_extractions,
                              s.profile_sha256, s.score_payload
                       from public.posting_scores s
                       join public.postings p on p.id = s.posting_id
                       left join public.posting_extractions e on e.posting_id = p.id
                       where s.profile_sha256 = %s
                         and {selection} and p.id > %s
                       order by p.id limit %s"""
                    + (' for update of p, s' if apply else ''),
                    (profile_sha256, last_id, batch_size),
                ).fetchall()
            if not rows:
                break
            planned = list(plan_rows(rows, profile, profile_sha256, recompute_unknown=recompute_unknown))
            for row, decision in planned:
                counts[decision['eligibility']] += 1
                if len(samples) < 20:
                    samples.append(dict(id=str(row['id']), company=row['company'],
                                        location=row['location'], decision=decision['eligibility'],
                                        reason=decision['eligibility_reason']))
            if apply:
                applied += apply_rows(connection, planned, profile_sha256, recompute_unknown=recompute_unknown)
            planned_count += len(planned)
            batches += 1
            last_id = rows[-1]['id']
    return dict(dry_run=not apply, recompute_unknown=recompute_unknown, batches=batches, planned=planned_count,
                counts=dict(counts), applied=applied,
                skipped_race=planned_count-applied if apply else 0, samples=samples)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--dry-run', action='store_true', help='Read-only preview (default)')
    mode.add_argument('--apply', action='store_true', help='Merge eligibility into missing payloads')
    parser.add_argument('--recompute-unknown', action='store_true',
                        help='Recompute only current-profile unknown eligibility; preserve known values')
    parser.add_argument('--batch-size', type=int, default=100)
    args = parser.parse_args(argv)
    database_url = os.environ.get('DATABASE_URL', '').strip()
    if not database_url:
        parser.error('DATABASE_URL is required')
    try:
        with psycopg.connect(database_url, autocommit=True) as connection:
            options = dict(apply=args.apply, batch_size=args.batch_size)
            if args.recompute_unknown:
                options['recompute_unknown'] = True
            receipt = backfill_connection(connection, **options)
    except (ValueError, psycopg.Error):
        # libpq and server errors can contain credentials or source values.
        print('Eligibility backfill failed; check connectivity, profile, migration 0037 and locks. '
              'Earlier committed batches are safe to resume.', file=sys.stderr)
        return 1
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
