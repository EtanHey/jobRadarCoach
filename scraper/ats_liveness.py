"""Conclusive ATS availability from complete, unfiltered public tenant boards."""

import json
import re
import time
from datetime import datetime, timezone
from urllib.parse import urlparse
from urllib.request import Request

from scraper.public_https import pinned_open
from scraper.source_registry import detect_supported_ats
from scraper.sources.comeet import POSITIONS_PATTERN
from scraper.sources.workable import DETAIL_PATTERN

ATS_SOURCES = ("greenhouse", "lever", "comeet", "workable", "ashby", "smartrecruiters", "workday")
USER_AGENT = "JobRadarCoach/1.0 (+https://jobradarcoach.vercel.app)"
IDENTIFIER = re.compile(r"[A-Za-z0-9_.-]{1,200}")


def public_get(*, clock=time.monotonic, sleep=time.sleep):
    """One GET/second/host, pinned public DNS, no redirects, bounded body/time."""
    last = {}
    def get(url):
        host = urlparse(url).hostname
        if host in last:
            sleep(max(0, 1 - (clock() - last[host])))
        try:
            request = Request(url, headers={"User-Agent": USER_AGENT}, method="GET")
            with pinned_open(request, timeout=10) as response:
                body = response.read(2_000_001)
            if len(body) > 2_000_000:
                raise ValueError("board exceeds response cap")
            return body.decode("utf-8")
        finally:
            last[host] = clock()
    return get


def board_identity(posting):
    source = posting["source"]
    prefix, tenant, job = str(posting.get("external_id") or posting.get("id", "")).split(":")
    if prefix != source or not all(IDENTIFIER.fullmatch(v) for v in (tenant, job)):
        raise ValueError("invalid stored identity")
    detected = next((t for url in (posting.get("apply_url"), posting.get("url"))
                     if url and (t := detect_supported_ats(str(url)))), None)
    if detected and detected["source"] != source:
        raise ValueError("source mismatch")
    region = ""
    if source == "comeet":
        if not detected or detected["identifiers"]["company_uid"] != tenant:
            raise ValueError("Comeet requires matching slug/company uid")
        slug = detected["identifiers"]["slug"]
        return source, f"{slug}/{tenant}", job, f"https://www.comeet.com/jobs/{slug}/{tenant}"
    if detected:
        identifiers = detected["identifiers"]
        if identifiers["board" if source == "greenhouse" else "account"] != tenant:
            raise ValueError("tenant mismatch")
        region = identifiers.get("region", "")
    if source == "greenhouse":
        # Greenhouse's documented public API is shared by US/EU hosted boards.
        url = f"https://boards-api.greenhouse.io/v1/boards/{tenant}/jobs"
    elif source == "lever":
        region = "eu" if any(urlparse(str(posting.get(k) or "")).hostname == "jobs.eu.lever.co"
                             for k in ("apply_url", "url")) else ""
        host = "api.eu.lever.co" if region else "api.lever.co"
        url = f"https://{host}/v0/postings/{tenant}?mode=json"
    elif source == "workable":
        url = f"https://apply.workable.com/{tenant}/jobs.md"
    else:
        raise ValueError("adapter not yet available")
    return source, (f"eu:{tenant}" if region else tenant), job, url


def active_ids(source, body, tenant=None):
    if source == "workable":
        if not re.search(r"^# .*All Open Positions", body, re.M) or "| Posted | Details |" not in body:
            raise ValueError("missing complete Workable board")
        rows = [line for line in body.splitlines() if line.startswith("|")
                and "| Title |" not in line and not re.fullmatch(r"[| :\-]+", line)]
        if any(not DETAIL_PATTERN.search(line) for line in rows) or re.search(r"[?&]page=", body):
            raise ValueError("incomplete Workable board")
        if tenant and any(f"https://apply.workable.com/{tenant}/jobs/view/" not in line for line in rows):
            raise ValueError("Workable tenant mismatch")
        return set(DETAIL_PATTERN.findall(body))
    if source == "comeet":
        match = POSITIONS_PATTERN.search(body)
        if not match:
            raise ValueError("missing Comeet positions")
        records, key = json.loads(match.group(1)), "uid"
    else:
        payload = json.loads(body)
        records = payload["jobs"] if source == "greenhouse" else payload
        key = "id"
        if source == "greenhouse" and (type(payload.get("meta", {}).get("total")) is not int
                                       or payload["meta"]["total"] != len(records)):
            raise ValueError("incomplete Greenhouse board")
    if not isinstance(records, list) or any(not isinstance(r, dict)
            or type(r.get(key)) not in (str, int) or not IDENTIFIER.fullmatch(str(r[key])) for r in records):
        raise ValueError("invalid board records")
    ids = {str(r[key]) for r in records}
    if len(ids) != len(records):
        raise ValueError("duplicate board identifiers")
    return ids


class BoardChecker:
    """Cache one complete snapshot per tenant; partial/failed boards stay unknown."""
    def __init__(self, fetcher=None):
        self.fetcher = fetcher or public_get()
        self.cache = {}

    def __call__(self, posting):
        checked_at = datetime.now(timezone.utc).isoformat()
        url = str(posting.get("url") or "")
        alive, reason, status = None, "invalid-ats-identity", None
        try:
            source, tenant, job, url = board_identity(posting)
            key = source, tenant
            if key not in self.cache:
                ids, error = None, None
                try:
                    if source == "lever":
                        ids = set()
                        for offset in range(0, 1000, 50):
                            page = active_ids(source, self.fetcher(f"{url}&skip={offset}&limit=50"))
                            if ids.intersection(page):
                                raise ValueError("repeated Lever page")
                            ids.update(page)
                            if len(page) < 50:
                                break
                        else:
                            raise ValueError("Lever page cap reached")
                    else:
                        ids = active_ids(source, self.fetcher(url), tenant)
                except Exception as exc:
                    ids, error = None, f"board-unknown:{type(exc).__name__}"
                self.cache[key] = ids, error, checked_at
            ids, error, checked_at = self.cache[key]
            if ids is not None:
                alive, reason, status = job in ids, "ats-active-list-present" if job in ids else "ats-active-list-absent", 200
            else:
                reason = error
        except (KeyError, TypeError, ValueError):
            pass
        return {"alive": alive, "liveness_reason": reason, "liveness_status": status,
                "liveness_final_url": url, "liveness_checked_at": checked_at}
