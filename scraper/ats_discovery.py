"""Probe public ATS boards for companies already known to the radar.

Comeet requires an opaque company UID, so it is probed only when a public
Comeet board URL accompanies the company name. No UID is guessed.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import time
import unicodedata
from http.client import HTTPException
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from scraper import source_registry
from scraper.sources import comeet, greenhouse, lever, workable


ROOT = Path(__file__).resolve().parent
CACHE_PATH = ROOT / "ats-probe-cache.json"
STOP = {"app", "jobs", "career", "careers", "company", "inc", "ltd", "israel"}
SUFFIX = {"ltd", "limited", "inc", "corp", "corporation", "technologies", "בעמ"}
ALIASES = {"jeen.ai": "jeenai", "4m analytics": "4manalytics"}
HOSTS = {
    "greenhouse": "boards-api.greenhouse.io",
    "lever": "api.lever.co",
    "workable": "apply.workable.com",
    "comeet": "www.comeet.com",
}
COMEET_URL = re.compile(
    r"^https://www\.comeet\.com/jobs/([A-Za-z0-9._-]+)/([A-Za-z0-9._-]+)/*$"
)


def key(name: str) -> str:
    folded = unicodedata.normalize("NFKD", name.casefold()).replace('בע"מ', "בעמ")
    folded = "".join(ch for ch in folded if not unicodedata.combining(ch))
    return " ".join(re.findall(r"[\w]+", folded, re.UNICODE))


def company_matches(wanted: str, observed: str) -> bool:
    a = [part for part in key(wanted).split() if part not in SUFFIX]
    b = [part for part in key(observed).split() if part not in SUFFIX]
    if not a or not b or a[0] in STOP or b[0] in STOP:
        return False
    # Exact core identity, allowing punctuation and legal suffix variation.
    return a == b or "".join(a) == "".join(b)


def slugs(name: str) -> list[str]:
    words = [word for word in key(name).split() if word not in SUFFIX]
    if not words or words[0] in STOP:
        return []
    values = [
        "-".join(words),
        "-".join(words) + "-israel",
        "".join(words) + "israel",
        "_".join(words),
        "".join(words),
    ]
    alias = ALIASES.get(name.casefold())
    if alias:
        values.insert(0, alias)
    return list(
        dict.fromkeys(value for value in values if re.fullmatch(r"[a-z0-9_-]+", value))
    )


def skip_miss(record: object, today: date) -> bool:
    if not isinstance(record, dict) or record.get("result") != "miss":
        return False
    try:
        return 0 <= (today - date.fromisoformat(record["last_checked_at"])).days < 30
    except (KeyError, TypeError, ValueError):
        return False


def merge(registry: dict, candidates: list[dict]) -> dict:
    """Append unique candidates; keep every existing entry byte-for-byte equivalent."""
    result = {**registry, "tenants": list(registry["tenants"])}
    seen = {_identity(row) for row in result["tenants"]}
    for row in candidates:
        identity = _identity(row)
        if identity not in seen:
            result["tenants"].append(row)
            seen.add(identity)
    return result


def _identity(row: dict) -> tuple:
    if row["source"] == "greenhouse":
        return ("greenhouse", str(row["identifiers"]["board"]).casefold())
    return source_registry._tenant_key(row)


@dataclass
class ProbeResult:
    tenant: dict | None = None
    result: str = "miss"
    slug_tried: str = ""
    rejected_by_name: int = 0


class RateLimited(RuntimeError):
    """This ATS host rejected the run; leave other hosts available."""


class Fetcher:
    """Bounded public GET transport, at most two requests per host per second."""

    def __init__(self):
        self.last: dict[str, float] = {}
        self.blocked_hosts: set[str] = set()
        self.opener = build_opener(_NoRedirect)

    def __call__(self, url: str) -> str | None:
        host = urlparse(url).hostname
        if host not in set(HOSTS.values()) | {"jobs.lever.co"}:
            raise ValueError("unexpected probe host")
        if host in self.blocked_hosts:
            raise RateLimited(f"{host} rate limited this run")
        gap = 2.0 if host == "apply.workable.com" else 0.5
        delay = self.last.get(host, 0) + gap - time.monotonic()
        if delay > 0:
            time.sleep(delay)
        self.last[host] = time.monotonic()
        for attempt in range(2):
            try:
                request = Request(
                    url,
                    headers={
                        "User-Agent": "Mozilla/5.0 (compatible; jobRadarCoach/1.0; +https://etanheyman.com)"
                    },
                )
                with self.opener.open(request, timeout=12) as response:
                    if response.status != 200:
                        raise RuntimeError(f"unexpected HTTP {response.status}")
                    limit = 65_536 if host == "jobs.lever.co" else 8_000_000
                    return response.read(limit).decode("utf-8")
            except HTTPError as error:
                if error.code == 429:
                    retry_after = error.headers.get("Retry-After", "0")
                    seconds = int(retry_after) if retry_after.isdigit() else 60
                    if attempt == 0 and seconds <= 30:
                        time.sleep(max(1, seconds))
                        continue
                    self.blocked_hosts.add(host)
                    raise RateLimited(f"{host} rate limited this run") from error
                if error.code in (404, 410):
                    return None
                if error.code not in (429, 500, 502, 503, 504) or attempt:
                    raise
            except (OSError, HTTPException):
                if attempt:
                    raise
            time.sleep(1)
        return None


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        raise RuntimeError("ATS endpoint redirected")


def _lever_name(page: str) -> str:
    match = re.search(r'<meta\s+property="og:title"\s+content="([^"]+)"', page, re.I)
    if match:
        return re.sub(
            r"\s+jobs\s*$", "", html.unescape(match.group(1)), flags=re.I
        ).strip()
    return ""


def _candidate(
    source: str, identifiers: dict[str, str], company: str, url: str, today: date
) -> dict:
    return {
        "source": source,
        "identifiers": identifiers,
        "company": company,
        "careers_url": source_registry._expected_careers_url(source, identifiers),
        "provenance": [{"kind": "auto-discovery-probe", "reference": url}],
        "last_verified_at": today.isoformat(),
        "enabled": True,
    }


def probe(
    name: str, source: str, fetch, *, today: date | None = None, comeet_url: str = ""
) -> ProbeResult:
    today = today or datetime.now(timezone.utc).date()
    result = ProbeResult()
    if source == "comeet":
        match = COMEET_URL.fullmatch(comeet_url)
        if not match:
            return result
        variants = [
            (match.group(1), {"slug": match.group(1), "company_uid": match.group(2)})
        ]
    else:
        candidates = slugs(name)
        if source == "lever":
            # Lever account paths are case-sensitive (Zadara is 200, zadara 404).
            raw = re.sub(r"\s+", "-", name.strip())
            if re.fullmatch(r"[A-Za-z0-9._-]+", raw):
                candidates = list(dict.fromkeys([raw, *candidates]))
        variants = [
            (slug, {"board" if source == "greenhouse" else "account": slug})
            for slug in candidates
        ]
    for slug, identifiers in variants:
        result.slug_tried = slug
        if source == "greenhouse":
            url = (
                f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=false"
            )
        elif source == "lever":
            url = f"https://api.lever.co/v0/postings/{slug}?mode=json"
        elif source == "workable":
            url = f"https://apply.workable.com/{slug}/jobs.md"
        elif source == "comeet":
            url = comeet_url
        else:
            raise ValueError(f"unsupported ATS: {source}")
        try:
            body = fetch(url)
            if body is None:
                continue
            observed = ""
            if source == "greenhouse":
                payload = json.loads(body)
                jobs = payload.get("jobs", [])
                if any(
                    isinstance(job, dict)
                    and urlparse(str(job.get("absolute_url", ""))).hostname
                    in {"job-boards.eu.greenhouse.io", "boards.eu.greenhouse.io"}
                    for job in jobs
                ):
                    identifiers["region"] = "eu"
                observed = next(
                    (
                        str(job.get("company_name", ""))
                        for job in jobs
                        if isinstance(job, dict) and job.get("company_name")
                    ),
                    "",
                )
                parsed = greenhouse.fetch(
                    {**identifiers, "company": name},
                    fetcher=lambda _: body,
                    before_request=lambda: None,
                )
            elif source == "lever":
                parsed = lever.fetch(
                    {**identifiers, "company": name},
                    fetcher=lambda _: body,
                    before_request=lambda: None,
                )
                if parsed:
                    page = fetch(f"https://jobs.lever.co/{slug}")
                    observed = _lever_name(page or "")
            elif source == "workable":
                heading = re.search(
                    r"^#\s+(.+?)\s+[—–-]\s+All Open Positions\s*$", body, re.M
                )
                observed = heading.group(1) if heading else ""
                accepted = False

                def first_only(_):
                    nonlocal accepted
                    if accepted:
                        return False
                    accepted = True
                    return True

                parsed = workable.fetch(
                    {**identifiers, "company": name},
                    fetcher=lambda board_url: (
                        body if board_url.endswith("/jobs.md") else ""
                    ),
                    before_request=lambda: None,
                    posting_filter=first_only,
                )
            else:
                parsed = comeet.fetch(
                    {**identifiers, "company": name},
                    fetcher=lambda _: body,
                    before_request=lambda: None,
                )
                positions = comeet.POSITIONS_PATTERN.search(body)
                match_names = (
                    [
                        row.get("company_name")
                        for row in json.loads(positions.group(1))
                        if isinstance(row, dict)
                    ]
                    if positions
                    else []
                )
                observed = str(next((value for value in match_names if value), ""))
            if not parsed:
                continue
            if not company_matches(name, observed):
                result.rejected_by_name += 1
                continue
            result.tenant = _candidate(source, identifiers, name, url, today)
            result.result = "hit"
            return result
        except RateLimited:
            result.result = "error"
            break
        except (
            ValueError,
            TypeError,
            KeyError,
            RuntimeError,
            OSError,
            HTTPException,
        ):
            result.result = "error"
    return result


def _names(path: str) -> list[tuple[str, str]]:
    if path == "db":
        import os
        import psycopg

        with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
            connection.read_only = True
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT DISTINCT company FROM postings WHERE company IS NOT NULL ORDER BY company"
                )
                return [(row[0], "") for row in cursor.fetchall()]
    rows = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.startswith("#"):
            name, _, hint = line.partition("\t")
            rows.append((name.strip(), hint.strip()))
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--names",
        required=True,
        help="UTF-8 names file (optional TAB Comeet URL), or db",
    )
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--merge", action="store_true")
    parser.add_argument("--cache", type=Path, default=CACHE_PATH)
    args = parser.parse_args()
    today = datetime.now(timezone.utc).date()
    cache = (
        json.loads(args.cache.read_text(encoding="utf-8"))
        if args.cache.exists()
        else {}
    )
    candidates = []
    stats = {
        source: {"hit": 0, "miss": 0, "error": 0, "rejected_by_name": 0}
        for source in HOSTS
    }
    fetch = Fetcher()
    for name, hint in dict(
        (key(name), (name, hint)) for name, hint in _names(args.names) if key(name)
    ).values():
        for source in HOSTS:
            if source == "comeet" and not COMEET_URL.fullmatch(hint):
                continue
            if HOSTS[source] in fetch.blocked_hosts:
                continue
            cache_key = f"{key(name)}|{source}"
            if skip_miss(cache.get(cache_key), today):
                continue
            outcome = probe(name, source, fetch, today=today, comeet_url=hint)
            stats[source][outcome.result] += 1
            stats[source]["rejected_by_name"] += outcome.rejected_by_name
            cache[cache_key] = {
                "result": outcome.result,
                "slug_tried": outcome.slug_tried,
                "last_checked_at": today.isoformat(),
            }
            if outcome.tenant:
                candidates.append(outcome.tenant)
            args.cache.write_text(
                json.dumps(cache, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
    registry = json.loads(source_registry.REGISTRY_PATH.read_text(encoding="utf-8"))
    output = (
        merge(registry, candidates)
        if args.merge
        else {"schema_version": 1, "tenants": candidates}
    )
    args.out.write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "names": len(_names(args.names)),
                "stats": stats,
                "registry_before": len(registry["tenants"]),
                "registry_after": len(merge(registry, candidates)["tenants"]),
                "rate_limited_hosts": sorted(fetch.blocked_hosts),
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
