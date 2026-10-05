"""Revisit stored public job URLs without changing application state or scores."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
import random
import time
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler

from scraper.liveness import check_url
from scraper.public_https import pinned_open
from scraper.ats_liveness import ATS_SOURCES, BoardChecker, check_posting_url, reliability_update, _counter


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        return None


PUBLIC_HOSTS = {
    "linkedin.com", "comeet.com", "greenhouse.io", "lever.co", "workable.com",
}
SELECT_STALE = """
with candidates as (
 select id, url, source, external_id, liveness,
 row_number() over (partition by source = 'linkedin'
   order by coalesce(liveness->>'last_attempt_at', ''), first_seen_at, id) as position
 from public.postings
 where source in ('linkedin', 'comeet', 'greenhouse', 'lever', 'workable', 'ashby', 'smartrecruiters', 'workday')
 and (%s = 'all' or (%s = 'linkedin') = (source = 'linkedin'))
)
select id, url, source, external_id, liveness from candidates
where source <> 'linkedin' or position <= %s
order by source, position
"""
UPDATE_RESULT = """
update public.postings set liveness = liveness || %s::jsonb
where id = %s and url = %s and source = %s and external_id = %s and liveness = %s::jsonb
"""


def public_job_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        return (
            parsed.scheme == "https" and parsed.port in (None, 443)
            and parsed.username is None and parsed.password is None
            and any(host == base or host.endswith("." + base) for base in PUBLIC_HOSTS)
        )
    except ValueError:
        return False


def recheck(connection, *, limit: int = 60, checker=None, board_checker=None, scope="all") -> dict:
    """All ATS tenants each run; only LinkedIn page polling has a rotating limit."""
    if not 1 <= limit <= 120 or scope not in ("all", "ats", "linkedin"):
        raise ValueError("limit must be 1..120 and scope all/ats/linkedin")
    def direct(posting):
        if checker is not None:
            return checker(posting["url"])
        time.sleep(1)  # Exceptional URL confirmations remain paced, never routine job polling.
        return check_posting_url(posting)
    board_checker = board_checker or BoardChecker()
    rows = connection.execute(SELECT_STALE, (scope, scope, limit)).fetchall()
    receipt = {"checked": 0, "closed": 0, "alive": 0, "unknown": 0, "unsupported": 0, "alerts": 0}
    for posting_id, url, source, external_id, state in rows:
        posting = {"source": source, "external_id": external_id, "url": url, "liveness": state}
        if source in ATS_SOURCES:
            result = board_checker(posting)
            update = reliability_update(posting, result, direct)
            receipt["alerts"] += update["ats_alert_count"] - _counter(state, "ats_alert_count")
        else:
            result = {"alive": None, "liveness_reason": "unsupported-public-url"}
            if not public_job_url(url):
                receipt["unsupported"] += 1
            else:
                try:
                    result = checker(url) if checker else check_url(url, opener=pinned_open, timeout=8)
                except Exception as error:
                    result = {"alive": None, "liveness_reason": type(error).__name__}
            update = {"last_attempt_at": datetime.now(timezone.utc).isoformat(),
                      "last_attempt_reason": result.get("liveness_reason", "unknown")}
            if result.get("alive") is False:
                update.update(result)
        written = connection.execute(UPDATE_RESULT, (json.dumps(update), posting_id, url, source,
                                                     external_id, json.dumps(state)))
        receipt["checked"] += 1
        if written.rowcount != 1:
            receipt["unknown"] += 1
        elif update.get("alive") is False:
            receipt["closed"] += 1
        elif result.get("alive") is True:
            receipt["alive"] += 1
        else:
            receipt["unknown"] += 1
    return receipt


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=60)
    parser.add_argument("--receipt", type=Path, default=Path("recheck-receipt.json"))
    parser.add_argument("--scope", choices=("all", "ats", "linkedin"), default="all")
    parser.add_argument("--jitter", action="store_true", help="Delay start by 0..60 seconds")
    args = parser.parse_args(argv)
    if args.jitter:
        time.sleep(random.uniform(0, 60))
    receipt = {"status": "failure"}
    try:
        import psycopg
        with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True,
                             connect_timeout=15) as connection:
            receipt = {"status": "success", **recheck(connection, limit=args.limit, scope=args.scope)}
    except Exception as error:
        receipt["error"] = type(error).__name__
    args.receipt.write_text(json.dumps(receipt) + "\n", encoding="utf-8")
    print(json.dumps(receipt))
    return 0 if receipt["status"] == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
