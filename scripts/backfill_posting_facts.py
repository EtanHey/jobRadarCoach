"""Bounded, localhost-only backfill for the derived posting facts table."""

from __future__ import annotations

from collections import Counter
import json
import os
from pathlib import Path
import sys
from urllib.parse import parse_qsl, urlsplit
from uuid import UUID

import psycopg
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import dict_row

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from classifier.facts import NORMALIZER_VERSION, normalize


_LOCAL_DATABASE_HOSTS = frozenset({"localhost", "127.0.0.1"})


def _local_host_list(value: object) -> bool:
    if not isinstance(value, str):
        return False
    hosts = [host.strip().lower() for host in value.split(",")]
    return bool(hosts) and all(host in _LOCAL_DATABASE_HOSTS for host in hosts)


def require_local_database_url(database_url: str) -> None:
    try:
        parsed = urlsplit(database_url)
        conninfo = conninfo_to_dict(database_url)
        url_host = parsed.hostname
    except (TypeError, ValueError, psycopg.Error) as error:
        raise ValueError("DATABASE_URL must use localhost or 127.0.0.1") from error

    query_hosts = [
        value for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if key.lower() in {"host", "hostaddr"}
    ]
    effective_hosts = [url_host, conninfo.get("host"), conninfo.get("hostaddr"), *query_hosts]
    environment_hosts = [os.environ.get("PGHOST"), os.environ.get("PGHOSTADDR")]
    if (
        parsed.scheme not in {"postgres", "postgresql"}
        or not _local_host_list(url_host)
        or any(value is not None and not _local_host_list(value) for value in (*effective_hosts, *environment_hosts))
    ):
        raise ValueError("DATABASE_URL must use localhost or 127.0.0.1")


def _empty_receipt() -> dict[str, object]:
    return {
        "normalizer_version": NORMALIZER_VERSION, "batches": 0, "rows_seen": 0,
        "rows_written": 0, "rows_skipped": 0, "work_mode_counts": {},
        "seniority_level_counts": {}, "unresolved_location_count": 0,
        "top_unresolved_locations": [],
    }


def backfill_connection(connection, *, batch_size: int = 100) -> dict[str, object]:
    if not 1 <= batch_size <= 1000:
        raise ValueError("batch_size must be between 1 and 1000")
    receipt = _empty_receipt()
    work_modes: Counter[str] = Counter()
    seniority_levels: Counter[str] = Counter()
    unresolved: Counter[str] = Counter()
    last_id = UUID(int=0)
    while True:
        with connection.cursor(row_factory=dict_row) as cursor:
            rows = cursor.execute(
                """select id, title, location, remote, seniority, stack, raw_jd, apply_url, url
                   from public.postings where id > %s order by id limit %s""",
                (last_id, batch_size),
            ).fetchall()
        if not rows:
            break
        receipt["batches"] = int(receipt["batches"]) + 1
        receipt["rows_seen"] = int(receipt["rows_seen"]) + len(rows)
        facts_by_id = {row["id"]: normalize(row) for row in rows}
        for facts in facts_by_id.values():
            work_modes[facts.work_mode] += 1
            seniority_levels[facts.seniority_level or "unknown"] += 1
            unresolved.update(facts.unresolved_locations)
        ids = list(facts_by_id)
        with connection.cursor(row_factory=dict_row) as cursor:
            existing = {
                row["posting_id"]: (row["normalizer_version"], row["facts_sha256"])
                for row in cursor.execute(
                    "select posting_id, normalizer_version, facts_sha256 from public.posting_facts where posting_id = any(%s)",
                    (ids,),
                ).fetchall()
            }
        changed = []
        for posting_id, facts in facts_by_id.items():
            if existing.get(posting_id) == (facts.normalizer_version, facts.facts_sha256):
                receipt["rows_skipped"] = int(receipt["rows_skipped"]) + 1
                continue
            output = facts.normalized_output()
            changed.append((posting_id, output["countries"], output["regions"], output["cities"],
                            output["work_mode"], output["seniority_level"], output["seniority_source"],
                            output["skills_mentioned"], output["link_status"], facts.normalizer_version,
                            facts.facts_sha256))
        if changed:
            with connection.cursor(row_factory=dict_row) as cursor:
                cursor.executemany(
                    """insert into public.posting_facts
                       (posting_id, countries, regions, cities, work_mode, seniority_level,
                        seniority_source, skills_mentioned, link_status, normalizer_version, facts_sha256)
                       values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                       on conflict (posting_id) do update set
                         countries = excluded.countries, regions = excluded.regions, cities = excluded.cities,
                         work_mode = excluded.work_mode, seniority_level = excluded.seniority_level,
                         seniority_source = excluded.seniority_source, skills_mentioned = excluded.skills_mentioned,
                         link_status = excluded.link_status, normalizer_version = excluded.normalizer_version,
                         facts_sha256 = excluded.facts_sha256, updated_at = pg_catalog.clock_timestamp()
                       where public.posting_facts.normalizer_version is distinct from excluded.normalizer_version
                          or public.posting_facts.facts_sha256 is distinct from excluded.facts_sha256""",
                    changed,
                )
            receipt["rows_written"] = int(receipt["rows_written"]) + len(changed)
        connection.commit()
        last_id = max(ids)
    receipt["work_mode_counts"] = dict(sorted(work_modes.items()))
    receipt["seniority_level_counts"] = dict(sorted(seniority_levels.items()))
    receipt["unresolved_location_count"] = sum(unresolved.values())
    receipt["top_unresolved_locations"] = [
        {"location": location, "count": count} for location, count in unresolved.most_common(20)
    ]
    return receipt


def backfill_database(database_url: str | None = None, *, batch_size: int = 100) -> dict[str, object]:
    value = (database_url if database_url is not None else os.environ.get("DATABASE_URL", "")).strip()
    require_local_database_url(value)
    with psycopg.connect(value, row_factory=dict_row) as connection:
        return backfill_connection(connection, batch_size=batch_size)


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default=None)
    parser.add_argument("--batch-size", type=int, default=100)
    args = parser.parse_args(argv)
    try:
        receipt = backfill_database(args.database_url, batch_size=args.batch_size)
    except (ValueError, psycopg.Error) as error:
        print(str(error), file=sys.stderr)
        return 2
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
