"""Bounded retry of missing stored descriptions from approved public job URLs."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import gzip
from io import BytesIO
import json
import os
from pathlib import Path
from urllib.request import Request, build_opener

from scraper.jd_fetch import BROWSER_USER_AGENT, MIN_PLAUSIBLE_JD_CHARS, extract_full_jd
from scraper.recheck import NoRedirect, public_job_url

MAX_ITEMS = 12
MAX_COMPRESSED_BYTES = 2_000_000
MAX_BODY_BYTES = 4_000_000
SELECT = """
select id, url from public.postings
where source in ('linkedin', 'comeet', 'greenhouse', 'lever', 'workable')
and (raw_jd is null or char_length(btrim(raw_jd)) < %s)
order by coalesce(liveness->>'description_fetch_attempt_at', ''), first_seen_at, id
limit %s
"""
UPDATE = """
update public.postings set raw_jd = case
when %s::text is not null and (raw_jd is null or char_length(btrim(raw_jd)) < %s)
then %s::text else raw_jd end, liveness = liveness || %s::jsonb
where id = %s and url = %s
"""


def _fetch(url: str, *, opener=None, timeout: int = 12) -> str:
    if not public_job_url(url):
        raise ValueError("unsupported-public-url")
    opener = opener or build_opener(NoRedirect()).open
    request = Request(url, headers={"User-Agent": BROWSER_USER_AGENT,
        "Accept": "text/html,application/xhtml+xml", "Accept-Encoding": "gzip"})
    with opener(request, timeout=min(timeout, 20)) as response:
        body = response.read(MAX_COMPRESSED_BYTES + 1)
        if len(body) > MAX_COMPRESSED_BYTES:
            raise ValueError("compressed-body-too-large")
        if str(response.headers.get("Content-Encoding", "")).casefold() == "gzip":
            with gzip.GzipFile(fileobj=BytesIO(body)) as stream:
                body = stream.read(MAX_BODY_BYTES + 1)
        if len(body) > MAX_BODY_BYTES:
            raise ValueError("body-too-large")
        charset = response.headers.get_content_charset() or "utf-8"
        description = extract_full_jd(body.decode(charset, errors="replace"))
    if len(description) < MIN_PLAUSIBLE_JD_CHARS:
        raise ValueError("description-missing-or-short")
    return description


def backfill(connection, *, limit: int = MAX_ITEMS, fetcher=_fetch) -> dict[str, int]:
    if not 1 <= limit <= MAX_ITEMS:
        raise ValueError("limit must be 1..12")
    rows = connection.execute(SELECT, (MIN_PLAUSIBLE_JD_CHARS, limit)).fetchall()
    receipt = {"attempted": 0, "stored": 0, "failed": 0, "unsupported": 0}
    for posting_id, url in rows:
        now = datetime.now(timezone.utc).isoformat()
        description = None
        try:
            description = fetcher(url)
            reason = "stored"
        except Exception as error:
            reason = str(error) if isinstance(error, ValueError) else type(error).__name__
            reason = reason if reason in {"unsupported-public-url", "compressed-body-too-large",
                "body-too-large", "description-missing-or-short"} else type(error).__name__
            receipt["unsupported" if reason == "unsupported-public-url" else "failed"] += 1
        metadata = {"description_fetch_attempt_at": now,
                    "description_fetch_attempt_reason": reason}
        connection.execute(UPDATE, (description, MIN_PLAUSIBLE_JD_CHARS, description,
                                    json.dumps(metadata), posting_id, url))
        receipt["attempted"] += 1
        if description is not None:
            receipt["stored"] += 1
    return receipt


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=MAX_ITEMS)
    parser.add_argument("--receipt", type=Path, default=Path("description-backfill-receipt.json"))
    args = parser.parse_args(argv)
    receipt: dict[str, object] = {"status": "failure"}
    try:
        import psycopg
        with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True,
                             connect_timeout=15) as connection:
            receipt = {"status": "success", **backfill(connection, limit=args.limit)}
    except Exception as error:
        receipt["error"] = type(error).__name__
    args.receipt.write_text(json.dumps(receipt) + "\n", encoding="utf-8")
    print(json.dumps(receipt))
    return 0 if receipt["status"] == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
