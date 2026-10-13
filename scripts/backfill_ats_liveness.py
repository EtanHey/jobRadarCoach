"""Dry-run ATS tags; explicit apply rechecks public boards before marking gone."""

import argparse
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from scraper.ats_liveness import ATS_SOURCES, BoardChecker, check_posting_url, reliability_update, _counter
from scraper.recheck import UPDATE_RESULT


def _validate_tag(tag):
    UUID(tag["posting_id"])
    checked = datetime.fromisoformat(tag["checked_at"].replace("Z", "+00:00"))
    if (tag["source"] not in ATS_SOURCES or tag["verdict"] not in ("alive", "gone", "unknown")
            or checked.tzinfo is None or not tag["external_id"].startswith(tag["source"] + ":")):
        raise ValueError("Invalid ATS tag")


def _validate_tags(tags):
    if not isinstance(tags, list):
        raise ValueError("Tags must be a list")
    identities = set()
    for tag in tags:  # Validate the entire batch before any network or mutation.
        _validate_tag(tag)
        if tag["posting_id"] in identities:
            raise ValueError("Duplicate posting identity")
        identities.add(tag["posting_id"])


def backfill(tags, *, connection=None, checker=None, url_checker=None):
    _validate_tags(tags)
    gone = [tag for tag in tags if tag["verdict"] == "gone"]
    receipt = {"tagged": len(tags), "gone": len(gone), "applied": 0, "dry_run": connection is None, "observed": 0, "alerts": 0}
    if connection is None:
        return receipt
    checker = checker or BoardChecker()
    def direct(posting):
        if url_checker is not None:
            return url_checker(posting)
        time.sleep(1)
        return check_posting_url(posting, board_checker=checker)
    for tag in gone:
        row = connection.execute("select id, url, source, external_id, liveness from public.postings "
            "where id = %s and source = %s and external_id = %s",
            (tag["posting_id"], tag["source"], tag["external_id"])).fetchone()
        if row is None:
            continue
        posting_id, url, source, external_id, state = row
        posting = {"source": source, "external_id": external_id, "url": url, "liveness": state}
        update = reliability_update(posting, checker(posting), direct)
        written = connection.execute(UPDATE_RESULT, (json.dumps(update), posting_id, url, source,
                                                     external_id, json.dumps(state)))
        receipt["observed"] += written.rowcount
        receipt["alerts"] += update["ats_alert_count"] - _counter(state, "ats_alert_count")
        if update.get("alive") is False:
            receipt["applied"] += written.rowcount
    return receipt


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tags", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    tags = json.loads(args.tags.read_text())
    receipt = backfill(tags)
    if args.apply:
        if datetime.now(timezone.utc) < datetime(2026, 10, 5, 15, tzinfo=timezone.utc):
            parser.error("Hosted mutation frozen until 2026-10-05 18:00 IDT")
        import psycopg
        with psycopg.connect(os.environ["DATABASE_URL"], connect_timeout=15) as connection:
            receipt = backfill(tags, connection=connection)
    print(json.dumps(receipt))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
