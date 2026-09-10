"""Revisit stored public job URLs without changing application state or scores."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, build_opener

from scraper.liveness import check_url


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        return None


PUBLIC_HOSTS = {
    "linkedin.com", "comeet.com", "greenhouse.io", "lever.co", "workable.com",
}
SELECT_STALE = """
select id, url from public.postings
where source in ('linkedin', 'comeet', 'greenhouse', 'lever', 'workable')
order by coalesce(liveness->>'last_attempt_at', ''), first_seen_at, id
limit %s
"""
UPDATE_RESULT = """
update public.postings set liveness = liveness || %s::jsonb
where id = %s and url = %s
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


def recheck(connection, *, limit: int = 60, checker=None) -> dict:
    """Round-robin bounded checks; unknown never erases a confirmed closure."""
    if not 1 <= limit <= 120:
        raise ValueError("limit must be 1..120")
    if checker is None:
        opener = build_opener(NoRedirect()).open

        def checker(url):
            return check_url(url, opener=opener, timeout=8)
    rows = connection.execute(SELECT_STALE, (limit,)).fetchall()
    receipt = {"checked": 0, "closed": 0, "unknown": 0, "unsupported": 0}
    for posting_id, url in rows:
        now = datetime.now(timezone.utc).isoformat()
        if not public_job_url(url):
            result = {"alive": None, "liveness_reason": "unsupported-public-url"}
            receipt["unsupported"] += 1
        else:
            try:
                result = checker(url)
            except Exception as error:
                result = {"alive": None, "liveness_reason": type(error).__name__}
        # Keep the last conclusive evidence separate from the latest attempt.
        update = {
            "last_attempt_at": now,
            "last_attempt_reason": result.get("liveness_reason", "unknown"),
        }
        if result.get("alive") is False:
            update.update(result)
            receipt["closed"] += 1
        else:
            receipt["unknown"] += 1
        connection.execute(UPDATE_RESULT, (json.dumps(update), posting_id, url))
        receipt["checked"] += 1
    return receipt


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=60)
    parser.add_argument("--receipt", type=Path, default=Path("recheck-receipt.json"))
    args = parser.parse_args(argv)
    receipt = {"status": "failure"}
    try:
        import psycopg
        with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True,
                             connect_timeout=15) as connection:
            receipt = {"status": "success", **recheck(connection, limit=args.limit)}
    except Exception as error:
        receipt["error"] = type(error).__name__
    args.receipt.write_text(json.dumps(receipt) + "\n", encoding="utf-8")
    print(json.dumps(receipt))
    return 0 if receipt["status"] == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
