"""Anonymous Ashby active-board API adapter; no detail-page liveness guesses."""
from __future__ import annotations

import html
import json
import re
from datetime import datetime, timezone
from typing import Callable
from urllib.parse import urlparse

USER_AGENT = "Mozilla/5.0 (compatible; JobRadarCoach/1.0)"


def active_ids(payload):
    """The nonpaginated public board is complete only if every membership is valid."""
    if not isinstance(payload, dict) or not isinstance(payload.get("jobs"), list):
        raise ValueError("invalid Ashby board")
    jobs = payload["jobs"]
    if any(payload.get(key) for key in ("hasMore", "next", "nextCursor", "nextPage", "pagination")):
        raise ValueError("incomplete Ashby board")
    if "total" in payload and (type(payload["total"]) is not int or payload["total"] != len(jobs)):
        raise ValueError("incomplete Ashby board")
    seen, active = set(), set()
    for job in jobs:
        if (not isinstance(job, dict) or not isinstance(job.get("id"), str)
                or not re.fullmatch(r"[A-Za-z0-9._-]{1,200}", job["id"])
                or type(job.get("isListed")) is not bool or job["id"] in seen):
            raise ValueError("invalid Ashby membership")
        seen.add(job["id"])
        if job["isListed"]:
            active.add(job["id"])
    return active


def _apply_url(value: object) -> str | None:
    if not isinstance(value, str) or re.search(r"[\s\\]", value):
        return None
    try:
        parsed = urlparse(value)
        return value if parsed.scheme == "https" and parsed.hostname and parsed.port != 0 and parsed.username is None else None
    except ValueError:
        return None


def _plain(value: object) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", value)).split()) if isinstance(value, str) else ""


def _published(value: object) -> tuple[str, str]:
    if not isinstance(value, str):
        return "", ""
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return "", ""
    if parsed.tzinfo is None:
        return "", ""
    return value, parsed.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _location(job: dict[str, object]) -> str:
    address = job.get("address")
    address = address.get("postalAddress", {}) if isinstance(address, dict) else {}
    locations = [{"location": job.get("location"), "address": address}]
    secondary = job.get("secondaryLocations")
    if isinstance(secondary, list):
        locations.extend(item for item in secondary if isinstance(item, dict))
    parts = []
    for item in locations:
        if isinstance(item.get("location"), str):
            parts.append(item["location"])
        address = item.get("address")
        country = address.get("addressCountry") if isinstance(address, dict) else None
        if isinstance(country, str):
            parts.append("Israel" if country.upper() in {"IL", "ISR", "ISRAEL"} else country)
    return "; ".join(dict.fromkeys(part.strip() for part in parts if part.strip()))


def _posting(job: object, query: dict[str, str], checked_at: str) -> dict[str, object] | None:
    if not isinstance(job, dict) or job.get("isListed") is not True:
        return None
    job_id, title, url = job.get("id"), job.get("title"), job.get("jobUrl")
    if not all(isinstance(value, str) and value.strip() for value in [job_id, title, url]):
        return None
    parsed = urlparse(url)
    if (parsed.scheme != "https" or parsed.netloc != "jobs.ashbyhq.com"
            or parsed.path.rstrip("/") != f"/{query['account']}/{job_id}"):
        return None
    jd = _plain(job.get("descriptionPlain")) or _plain(job.get("descriptionHtml"))
    posted_at, posted_ago = _published(job.get("publishedAt"))
    return {
        "id": f"ashby:{query['account']}:{job_id}", "source": "ashby",
        "title": title.strip(), "company": query.get("company", query["account"]),
        "location": _location(job),
        "remote": job.get("isRemote") if type(job.get("isRemote")) is bool else None,
        "url": url, "apply_url": _apply_url(job.get("applyUrl")),
        "posted_at": posted_at, "posted_ago": posted_ago,
        "jd_text": jd, "jd_fetched": bool(jd), "raw_text": title.strip(),
        "alive": True, "liveness_reason": "ashby-active-list",
        "liveness_checked_at": checked_at, "liveness_final_url": url,
    }


def fetch(query: dict[str, str], *, fetcher: Callable[[str], str | None],
          before_request: Callable[[], None]) -> list[dict[str, object]]:
    before_request()
    body = fetcher(f"https://api.ashbyhq.com/posting-api/job-board/{query['account']}")
    if body is None:
        raise RuntimeError("Ashby board request failed")
    payload = json.loads(body)
    if not isinstance(payload, dict) or not isinstance(payload.get("jobs"), list):
        raise ValueError("invalid Ashby board payload")
    checked_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return [row for job in payload["jobs"] if (row := _posting(job, query, checked_at)) is not None]
