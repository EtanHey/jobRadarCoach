"""Anonymous Greenhouse public-board JSON adapter."""

from __future__ import annotations

import html
import json
import logging
import re
from datetime import datetime, timezone
from typing import Callable


LOGGER = logging.getLogger("coach.jobfeed.source.greenhouse")


def _mapping(value: object) -> dict[str, object]:
    return value if isinstance(value, dict) else {}


def _plain(value: object) -> str:
    text = str(value)
    while True:
        decoded = html.unescape(text)
        if decoded == text:
            break
        text = decoded
    return " ".join(re.sub(r"<[^>]+>", " ", text).split())


def _posted_fields(value: object) -> tuple[str, str] | None:
    posted_at = str(value or "")
    try:
        parsed = datetime.fromisoformat(posted_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    return posted_at, parsed.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def fetch(
    query: dict[str, str],
    *,
    fetcher: Callable[[str], str | None],
    before_request: Callable[[], None],
) -> list[dict[str, object]]:
    board = query["board"]
    before_request()
    body = fetcher(
        f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true"
    )
    if body is None:
        raise RuntimeError("Greenhouse board request failed")
    payload = json.loads(body)
    if not isinstance(payload, dict):
        LOGGER.info("Skipping non-mapping Greenhouse payload for tenant %s", board)
        return []
    jobs = payload.get("jobs", [])
    if not isinstance(jobs, list):
        LOGGER.info("Skipping non-list Greenhouse records for tenant %s", board)
        return []
    postings: list[dict[str, object]] = []
    for job in jobs:
        if not isinstance(job, dict):
            LOGGER.info(
                "Skipping non-object Greenhouse record for tenant %s", board
            )
            continue
        job_id = job.get("id")
        if not job_id:
            LOGGER.info("Skipping Greenhouse posting without id for tenant %s", board)
            continue
        jd_text = _plain(job.get("content", ""))
        location = _mapping(job.get("location"))
        company = str(job.get("company_name") or query.get("company", board)).strip()
        posted_fields = _posted_fields(job.get("first_published"))
        posted_at, posted_ago = posted_fields or ("", "")
        postings.append(
            {
                "id": f"greenhouse:{board}:{job_id}",
                "title": str(job.get("title", "")),
                "company": company,
                "location": str(location.get("name", "")),
                "url": str(job.get("absolute_url", "")),
                "posted_at": posted_at,
                "posted_ago": posted_ago,
                "updated_at": str(job.get("updated_at") or ""),
                "source": "greenhouse",
                "raw_text": " ".join(
                    value
                    for value in (
                        str(job.get("title", "")),
                        company,
                        str(location.get("name", "")),
                    )
                    if value
                ),
                "jd_fetched": bool(jd_text),
                "jd_text": jd_text,
            }
        )
    return postings
