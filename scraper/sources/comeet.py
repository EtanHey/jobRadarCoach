"""Anonymous Comeet company-board adapter."""

from __future__ import annotations

import html
import json
import logging
import re
from datetime import datetime, timezone
from typing import Callable


POSITIONS_PATTERN = re.compile(
    r"COMPANY_POSITIONS_DATA = (\[.*?\]);\s*POSITION_DATA", re.S
)
LOGGER = logging.getLogger("coach.jobfeed.source.comeet")


def _mapping(value: object) -> dict[str, object]:
    return value if isinstance(value, dict) else {}


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
    slug = query["slug"]
    company_uid = query["company_uid"]
    before_request()
    body = fetcher(f"https://www.comeet.com/jobs/{slug}/{company_uid}")
    if body is None:
        raise RuntimeError("Comeet board request failed")
    match = POSITIONS_PATTERN.search(body)
    if match is None:
        raise RuntimeError("Comeet board omitted COMPANY_POSITIONS_DATA")

    # POSITIONS_PATTERN captures only array syntax; invalid JSON still raises.
    positions = json.loads(match.group(1))

    postings: list[dict[str, object]] = []
    for position in positions:
        if not isinstance(position, dict):
            LOGGER.info(
                "Skipping non-object Comeet record for tenant %s", company_uid
            )
            continue
        position_uid = position.get("uid")
        if not position_uid:
            LOGGER.info(
                "Skipping Comeet posting without uid for tenant %s", company_uid
            )
            continue
        details = _mapping(position.get("custom_fields")).get("details", [])
        if not isinstance(details, list):
            details = []
        jd_text = " ".join(
            _plain(item.get("value", ""))
            for item in details
            if isinstance(item, dict)
        ).strip()
        location = _mapping(position.get("location"))
        updated_fields = _posted_fields(position.get("time_updated"))
        updated_at, updated_display = updated_fields or ("", "")
        posting = {
            "id": f"comeet:{company_uid}:{position_uid}",
            "title": str(position.get("name", "")),
            "company": str(position.get("company_name", query.get("company", slug))),
            "location": str(location.get("displayName") or location.get("name") or ""),
            "url": str(position.get("url_comeet_hosted_page", "")),
            "updated_at": updated_at,
            "posted_ago": f"Updated {updated_display}" if updated_display else "",
            "source": "comeet",
            "raw_text": " ".join(
                str(value)
                for value in (
                    position.get("name", ""),
                    position.get("company_name", ""),
                    location.get("name", ""),
                )
                if value
            ),
            "jd_fetched": bool(jd_text),
            "jd_text": jd_text,
        }
        postings.append(posting)
    return postings
