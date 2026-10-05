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


def _stored_identity(posting):
    source = posting["source"]
    prefix, tenant, job = str(posting.get("external_id") or posting.get("id", "")).split(":")
    if prefix != source or not all(IDENTIFIER.fullmatch(v) for v in (tenant, job)):
        raise ValueError("invalid stored identity")
    return source, tenant, job


def _detected_board(posting):
    for field in ("apply_url", "url"):
        url = posting.get(field)
        if url:
            detected = detect_supported_ats(str(url))
            if detected is not None:
                return detected
    return None


def _comeet_identity(tenant, job, detected):
    if not detected or detected["identifiers"]["company_uid"] != tenant:
        raise ValueError("Comeet requires matching slug/company uid")
    slug = detected["identifiers"]["slug"]
    return "comeet", f"{slug}/{tenant}", job, f"https://www.comeet.com/jobs/{slug}/{tenant}"


def _region(source, tenant, detected):
    if not detected:
        return ""
    identifiers = detected["identifiers"]
    if identifiers["board" if source == "greenhouse" else "account"] != tenant:
        raise ValueError("tenant mismatch")
    return identifiers.get("region", "")


def _lever_region(posting):
    return "eu" if any(urlparse(str(posting.get(k) or "")).hostname == "jobs.eu.lever.co"
                       for k in ("apply_url", "url")) else ""


def board_identity(posting):
    source, tenant, job = _stored_identity(posting)
    detected = _detected_board(posting)
    if detected and detected["source"] != source:
        raise ValueError("source mismatch")
    if source == "comeet":
        return _comeet_identity(tenant, job, detected)
    region = _region(source, tenant, detected)
    if source == "greenhouse":
        # Greenhouse's documented public API is shared by US/EU hosted boards.
        url = f"https://boards-api.greenhouse.io/v1/boards/{tenant}/jobs"
    elif source == "lever":
        region = _lever_region(posting)
        host = "api.eu.lever.co" if region else "api.lever.co"
        url = f"https://{host}/v0/postings/{tenant}?mode=json"
    elif source == "workable":
        url = f"https://apply.workable.com/{tenant}/jobs.md"
    else:
        raise ValueError("adapter not yet available")
    return source, (f"eu:{tenant}" if region else tenant), job, url


def _workable_rows(body):
    if not re.search(r"^# .*All Open Positions", body, re.M) or "| Posted | Details |" not in body:
        raise ValueError("missing complete Workable board")
    return [line for line in body.splitlines() if line.startswith("|")
            and "| Title |" not in line and not re.fullmatch(r"[| :\-]+", line)]


def _workable_ids(body, tenant):
    for line in _workable_rows(body):
        if not DETAIL_PATTERN.search(line):
            raise ValueError("incomplete Workable board")
        if tenant and f"https://apply.workable.com/{tenant}/jobs/view/" not in line:
            raise ValueError("Workable tenant mismatch")
    if re.search(r"[?&]page=", body):
        raise ValueError("incomplete Workable board")
    return set(DETAIL_PATTERN.findall(body))


def _records(source, body):
    if source == "comeet":
        match = POSITIONS_PATTERN.search(body)
        if not match:
            raise ValueError("missing Comeet positions")
        return json.loads(match.group(1)), "uid"
    payload = json.loads(body)
    if source == "greenhouse":
        records = payload["jobs"]
        if (type(payload.get("meta", {}).get("total")) is not int
                or payload["meta"]["total"] != len(records)):
            raise ValueError("incomplete Greenhouse board")
        return records, "id"
    return payload, "id"


def _record_id(record, key):
    if not isinstance(record, dict) or type(record.get(key)) not in (str, int):
        raise ValueError("invalid board record")
    identifier = str(record[key])
    if not IDENTIFIER.fullmatch(identifier):
        raise ValueError("invalid board identifier")
    return identifier


def active_ids(source, body, tenant=None):
    if source == "workable":
        return _workable_ids(body, tenant)
    records, key = _records(source, body)
    if not isinstance(records, list):
        raise ValueError("invalid board records")
    ids = {_record_id(record, key) for record in records}
    if len(ids) != len(records):
        raise ValueError("duplicate board identifiers")
    return ids


class BoardChecker:
    """Cache one complete snapshot per tenant; partial/failed boards stay unknown."""
    def __init__(self, fetcher=None):
        self.fetcher = fetcher or public_get()
        self.cache = {}

    def _lever_lookup(self, url, job):
        # Offset pages are not a stable snapshot; undocumented misses are unknown.
        try:
            record = json.loads(self.fetcher(url))
            return True if _record_id(record, "id") == job else None
        except Exception:
            return None

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
                if source == "lever" and not alive:
                    url = f"{url.split('?')[0]}/{job}?mode=json"
                    alive = self._lever_lookup(url, job)
                    reason = "ats-posting-present" if alive else "lever-miss-unconfirmed"
                    status = 200 if alive else None
            else:
                reason = error
        except (KeyError, TypeError, ValueError):
            pass
        return {"alive": alive, "liveness_reason": reason, "liveness_status": status,
                "liveness_final_url": url, "liveness_checked_at": checked_at}
