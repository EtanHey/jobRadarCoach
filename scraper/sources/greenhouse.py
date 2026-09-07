"""Anonymous Greenhouse public-board JSON adapter."""

from __future__ import annotations

import html
import json
import re
from datetime import datetime, timezone
from typing import Callable


def _plain(value: object) -> str:
    return " ".join(
        html.unescape(re.sub(r"<[^>]+>", " ", str(value))).split()
    )


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
    postings: list[dict[str, object]] = []
    for job in payload.get("jobs", []):
        jd_text = _plain(job.get("content", ""))
        location = job.get("location") or {}
        company = str(job.get("company_name") or query.get("company", board)).strip()
        posted_fields = _posted_fields(job.get("first_published"))
        posted_at, posted_ago = posted_fields or ("", "")
        postings.append(
            {
                "id": f"greenhouse:{board}:{job['id']}",
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
