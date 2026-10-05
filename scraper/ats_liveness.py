"""Conclusive ATS availability from complete, unfiltered public tenant boards."""

import json
import re
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urljoin, urlparse
from urllib.request import Request
from urllib.error import HTTPError

from scraper.public_https import pinned_open
from scraper.ats_sources import ATS_SOURCES
from scraper.source_registry import detect_supported_ats
from scraper.sources.comeet import POSITIONS_PATTERN
from scraper.sources.workable import DETAIL_PATTERN

USER_AGENT = "JobRadarCoach/1.0 (+https://jobradarcoach.vercel.app)"
IDENTIFIER = re.compile(r"[A-Za-z0-9_.-]{1,200}")
BOARD_CAP = 2_000_000
LEVER_BOARD_CAP = 16_000_000
STRIKE_SPACING = timedelta(minutes=45)
URL_UNKNOWN_LIMIT = 3
URL_BACKOFF = timedelta(hours=24)


def public_get(*, clock=time.monotonic, sleep=time.sleep):
    """One GET/second/host, pinned public DNS, no redirects, bounded body/time."""
    last = {}
    def get(url):
        host = urlparse(url).hostname
        if host in last:
            sleep(max(0, 1 - (clock() - last[host])))
        try:
            request = Request(url, headers={"User-Agent": USER_AGENT}, method="GET")
            cap = LEVER_BOARD_CAP if host in {"api.lever.co", "api.eu.lever.co"} else BOARD_CAP
            with pinned_open(request, timeout=10) as response:
                body = bytearray()
                while True:
                    chunk = response.read(min(65_536, cap + 1 - len(body)))
                    if not chunk:
                        break
                    body.extend(chunk)
                    if len(body) > cap:
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
        region = ""  # US/EU job URLs share the same board snapshot.
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


REDIRECT_CODES = {301, 302, 303, 307, 308}


def _generic_careers_redirect(posting, final_url):
    original, final = urlparse(posting["url"]), urlparse(final_url)
    if (final.scheme != "https" or final.username or final.password
            or final.port not in (None, 443)):
        return False
    detected = detect_supported_ats(posting["url"])
    if detected or (posting["source"] == "lever" and original.hostname in {"jobs.lever.co", "jobs.eu.lever.co"}):
        source, tenant, _, _ = board_identity(posting)
        if source == "lever":
            tenant = _stored_identity(posting)[1]
        paths = {"greenhouse": f"/{tenant}", "lever": f"/{tenant}",
                 "comeet": f"/jobs/{tenant}", "workable": f"/{tenant}"}
        generic = paths.get(source)
        # Same tenant/origin only; auth, another tenant and job-specific redirects stay unknown.
        query = parse_qs(final.query, keep_blank_values=True)
        return (final.netloc.lower() == original.netloc.lower()
                and final.path.rstrip("/") == generic
                and (not query or query == {"error": ["true"]}))
    # Stored employer-hosted URLs may redirect within that employer's careers section.
    return (final.netloc.lower() == original.netloc.lower() and not final.query
            and final.path.rstrip("/") in {"/careers", "/jobs", "/careers/jobs"}
            and final_url != posting["url"])


def check_posting_url(posting):
    """Check the stored URL once; never follow or guess a redirect destination."""
    url = posting["url"]
    status, alive, reason, final_url = None, None, "posting-url-unknown", url
    try:
        parsed = urlparse(url)
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username
                or parsed.password or parsed.port not in (None, 443)):
            raise ValueError("invalid posting URL")
        request = Request(url, headers={"User-Agent": USER_AGENT}, method="GET")
        with pinned_open(request, timeout=10) as response:
            status = response.getcode()
    except HTTPError as error:
        status = error.code
        if status in (404, 410):
            alive, reason = False, f"http-{status}"
        elif status in REDIRECT_CODES:
            final_url = urljoin(url, error.headers.get("Location", ""))
            try:
                if _generic_careers_redirect(posting, final_url):
                    alive, reason = False, "ats-generic-careers-redirect"
            except (ValueError, KeyError, TypeError):
                pass
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return {"alive": alive, "liveness_status": status, "liveness_reason": reason,
            "liveness_final_url": final_url,
            "liveness_checked_at": datetime.now(timezone.utc).isoformat()}


def _counter(state, key):
    value = state.get(key, 0)
    return value if type(value) is int and value >= 0 else 0


def _timestamp(value):
    try:
        parsed = datetime.fromisoformat(value)
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else None
    except (ValueError, TypeError):
        return None


def _unknown_alert(state, update, reason, status=None, *, list_error=False):
    key = f"{reason}:{status}"
    if list_error or state.get("ats_unknown_reason") != key:
        update["ats_alert_count"] += 1
    update["ats_unknown_reason"] = key


def _list_miss(state, checked_at, current, update):
    previous = _counter(state, "ats_miss_count")
    observed = _timestamp(checked_at)
    if observed is None or observed > current:
        observed = current
    first = _timestamp(state.get("ats_first_miss_at") or state.get("ats_last_list_checked_at"))
    if previous == 0 or first is None or first > observed:
        first = observed
    update["ats_first_miss_at"] = first.isoformat()
    misses = 1 if previous < 2 and (previous == 0 or observed - first < STRIKE_SPACING) else 2
    update["ats_miss_count"] = misses
    return misses


def _confirm_absence(posting, state, update, direct_checker, current):
    next_check = _timestamp(state.get("ats_url_next_check_at"))
    if next_check is not None and current < next_check:
        update["last_attempt_reason"] = "posting-url-backoff"
        return
    try:
        direct = direct_checker(posting)
    except Exception as error:
        direct = {"alive": None, "liveness_reason": type(error).__name__}
    update["last_attempt_reason"] = direct.get("liveness_reason", "posting-url-unknown")
    update["ats_url_last_attempt_at"] = current.isoformat()
    if direct.get("alive") is False and (direct.get("liveness_status") in (404, 410)
            or direct.get("liveness_reason") == "ats-generic-careers-redirect"):
        update.update(direct)
        update.update(last_attempt_verdict="gone", ats_unknown_reason=None,
                      ats_url_unknown_count=0, ats_url_next_check_at=None)
    else:
        unknowns = min(URL_UNKNOWN_LIMIT, _counter(state, "ats_url_unknown_count") + 1)
        update.update(ats_url_unknown_count=unknowns,
                      ats_url_next_check_at=(current + URL_BACKOFF).isoformat()
                      if unknowns >= URL_UNKNOWN_LIMIT else None)
        _unknown_alert(state, update, update["last_attempt_reason"], direct.get("liveness_status"))


def reliability_update(posting, result, direct_checker):
    """Persist list strikes separately from conclusive availability; errors break the streak."""
    state = posting.get("liveness", {})
    current = datetime.now(timezone.utc)
    now = current.isoformat()
    update = {"last_attempt_at": now, "last_attempt_reason": result.get("liveness_reason", "unknown"),
              "last_attempt_verdict": "unknown", "ats_alert_count": _counter(state, "ats_alert_count")}
    checked_at = result.get("liveness_checked_at", now)
    if checked_at == state.get("ats_last_list_checked_at"):
        update["last_attempt_verdict"] = "duplicate-snapshot"
        return update
    update["ats_last_list_checked_at"] = checked_at
    if result.get("alive") is True:
        # A board API URL is membership evidence, not a posting's own-URL evidence.
        update.update({key: value for key, value in result.items() if key != "liveness_final_url"})
        update.update(ats_miss_count=0, ats_last_seen_in_list=result.get("liveness_checked_at", now),
                      ats_first_miss_at=None, ats_url_unknown_count=0, ats_url_next_check_at=None,
                      ats_url_last_attempt_at=None, ats_unknown_reason=None, last_attempt_verdict="alive")
    elif result.get("alive") is False:
        if _list_miss(state, checked_at, current, update) < 2:
            update.update(last_attempt_verdict="pending", ats_unknown_reason=None)
        elif state.get("alive") is False:
            update.update(alive=False, last_attempt_verdict="gone")
        else:
            _confirm_absence(posting, state, update, direct_checker, current)
    else:
        update.update(ats_miss_count=0, ats_first_miss_at=None)
        _unknown_alert(state, update, update["last_attempt_reason"], result.get("liveness_status"),
                       list_error=update["last_attempt_reason"].startswith("board-unknown:"))
    return update
