"""Infer missing work modes from stored location labels; dry-run by default."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
import os

import psycopg
from psycopg.rows import dict_row

from scraper.work_mode import location_mode


def candidates(rows):
    for row in rows:
        if row.get('work_mode') is None and row.get('remote') is None:
            if mode := location_mode(row.get('location')):
                yield row, mode


def backfill(connection, rows, *, apply=False):
    planned = list(candidates(rows))
    counts = Counter(f"{row['source']}:unspecified->{mode}" for row, mode in planned)
    applied = 0
    if apply:
        for row, mode in planned:
            result = connection.execute(
                "update public.postings set work_mode=%s,work_mode_source='location',remote=%s "
                "where id=%s and remote is null and work_mode is null "
                "and location is not distinct from %s",
                (mode, {'remote': True, 'on-site': False}.get(mode), row['id'], row['location']),
            )
            applied += result.rowcount
    return dict(scanned=len(rows), planned=len(planned), changes=dict(sorted(counts.items())),
                applied=applied, skipped_race=len(planned)-applied if apply else 0,
                examples=[dict(id=str(row['id']), source=row['source'], location=row['location'],
                               before='unspecified', after=mode) for row, mode in planned[:20]])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true', help='Lead only, after migration apply')
    arguments = parser.parse_args()
    if arguments.apply and datetime.now(timezone.utc) < datetime(2026, 10, 5, 15, tzinfo=timezone.utc):
        parser.error('Production freeze: apply is unavailable before 18:00 IDT on 2026-10-05')
    # Read modes via JSON so dry-run also works before the additive migration.
    with psycopg.connect(os.environ['DATABASE_URL'], row_factory=dict_row) as connection:
        if not arguments.apply:
            connection.execute('set transaction read only')
        rows = connection.execute(
            "select id,source,location,remote,to_jsonb(p)->>'work_mode' work_mode "
            "from public.postings p order by source,id"
        ).fetchall()
        result = backfill(connection, rows, apply=arguments.apply)
        if not arguments.apply:
            connection.rollback()
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
