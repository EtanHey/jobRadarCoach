"""Anonymous Lever public-postings JSON adapter."""

from __future__ import annotations

import html
import json
import logging
import re
from datetime import datetime, timezone
from typing import Callable


LOGGER = logging.getLogger("coach.jobfeed.source.lever")


def _mapping(value: object) -> dict[str, object]:
    return value if isinstance(value, dict) else {}


def _plain(value: object) -> str:
    return " ".join(
        html.unescape(re.sub(r"<[^>]+>", " ", str(value))).split()
    )


def _posted_fields(value: object) -> tuple[str, str] | None:
    try:
        parsed = datetime.fromtimestamp(float(value) / 1000, timezone.utc)
    except (TypeError, ValueError, OverflowError):
        return None
    posted_at = parsed.isoformat().replace("+00:00", "Z")
    return posted_at, parsed.strftime("%Y-%m-%d %H:%M UTC")


def fetch(
    query: dict[str, str],
    *,
    fetcher: Callable[[str], str | None],
    before_request: Callable[[], None],
) -> list[dict[str, object]]:
    account = query["account"]
    company = query.get("company", account)
    before_request()
    body = fetcher(f"https://api.lever.co/v0/postings/{account}?mode=json")
    if body is None:
        raise RuntimeError("Lever board request failed")
    jobs = json.loads(body)
    if not isinstance(jobs, list):
        LOGGER.info("Skipping non-list Lever records for tenant %s", account)
        return []
    postings: list[dict[str, object]] = []
    for job in jobs:
        if not isinstance(job, dict):
            LOGGER.info("Skipping non-object Lever record for tenant %s", account)
            continue
        job_id = job.get("id")
        if not job_id:
            LOGGER.info("Skipping Lever posting without id for tenant %s", account)
            continue
        lists = job.get("lists", [])
        if not isinstance(lists, list):
            lists = []
        list_text = " ".join(
            _plain(item.get("text", "")) + " " + _plain(item.get("content", ""))
            for item in lists
            if isinstance(item, dict)
        )
        jd_text = " ".join(
            value
            for value in (
                _plain(job.get("descriptionPlain", "")),
                _plain(job.get("openingPlain", "")),
                list_text.strip(),
                _plain(job.get("additionalPlain", "")),
            )
            if value
        )
        categories = _mapping(job.get("categories"))
        location = str(categories.get("location") or "")
        posted_fields = _posted_fields(job.get("createdAt"))
        posted_at, posted_ago = posted_fields or ("", "")
        postings.append(
            {
                "id": f"lever:{account}:{job_id}",
                "title": str(job.get("text", "")),
                "company": company,
                "location": location,
                "url": str(job.get("hostedUrl", "")),
                "posted_at": posted_at,
                "posted_ago": posted_ago,
                "source": "lever",
                "raw_text": " ".join(
                    value for value in (str(job.get("text", "")), company, location) if value
                ),
                "jd_fetched": bool(jd_text),
                "jd_text": jd_text,
            }
        )
    return postings
