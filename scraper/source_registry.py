#!/usr/bin/env python3
"""Validate and inspect the checked-in public ATS tenant registry."""

from __future__ import annotations

import argparse
import csv
import html
import ipaddress
import json
import re
from socket import SOCK_STREAM, getaddrinfo
from datetime import date, datetime, timezone
from pathlib import Path
from html.parser import HTMLParser
from time import monotonic
from typing import Callable
from urllib.parse import unquote, urljoin, urlparse, urlunparse
from urllib.request import HTTPRedirectHandler, Request, build_opener


REGISTRY_PATH = Path(__file__).with_name("source-registry.json")
DEFAULT_MAX_AGE_DAYS = 45
IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9._-]+$")
ENTRY_FIELDS = {
    "source",
    "identifiers",
    "company",
    "careers_url",
    "provenance",
    "last_verified_at",
    "enabled",
}
IDENTIFIER_FIELDS = {
    "comeet": (("slug", "company_uid"), ()),
    "greenhouse": (("board",), ("region",)),
    "lever": (("account",), ()),
    "workable": (("account",), ()),
}
CAREERS_HOSTS = {
    "comeet": {"comeet.com", "www.comeet.com"},
    "greenhouse": {
        "boards.greenhouse.io",
        "boards.eu.greenhouse.io",
        "job-boards.greenhouse.io",
        "job-boards.eu.greenhouse.io",
    },
    "lever": {"jobs.lever.co"},
    "workable": {"apply.workable.com"},
}
MARKDOWN_LINK_RE = re.compile(r"\[[^\]]*\]\((https?://[^)\s]+)\)")
RAW_URL_RE = re.compile(r"https?://[^\s)>|]+")
HYPERLINK_RE = re.compile(r'^=HYPERLINK\("([^"]+)","([^"]*)"\)$', re.I)
CAREER_LINK_HINT_RE = re.compile(r"(?:career|jobs?|join[-_]?us|opening|position)", re.I)
WORKABLE_HEADING_RE = re.compile(r"^#\s+.+\s+[—–-]\s+All Open Positions\s*$")
WORKABLE_TABLE_HEADER_RE = re.compile(
    r"^\|\s*Title\s*\|\s*Department\s*\|\s*Location\s*\|\s*Type\s*\|"
    r"\s*Salary\s*\|\s*Posted\s*\|\s*Details\s*\|$"
)
WORKABLE_TABLE_SEPARATOR_RE = re.compile(r"^\|(?:\s*:?-{3,}:?\s*\|){7}$")
WORKABLE_FOOTER = "Powered by [Workable](https://www.workable.com)"
RESOLVE_TIMEOUT_SECONDS = 15.0
FETCH_TIMEOUT_SECONDS = 20.0
# Apple Python 3.9's ipaddress tables predate these IANA non-public assignments.
IANA_NON_PUBLIC_FIXUPS = {
    4: (
        ipaddress.ip_network("192.0.0.0/24"),
        ipaddress.ip_network("192.88.99.2/32"),
    ),
    6: (
        ipaddress.ip_network("64:ff9b:1::/48"),
        ipaddress.ip_network("2002::/16"),
        ipaddress.ip_network("3fff::/20"),
    ),
}
IANA_PUBLIC_EXCEPTIONS = {
    4: (
        ipaddress.ip_network("192.0.0.9/32"),
        ipaddress.ip_network("192.0.0.10/32"),
    ),
    6: (),
}


class _BudgetExhausted(RuntimeError):
    pass


class UnsafeEgressError(ValueError):
    """A URL is not eligible for production network access."""


class _NetworkBudget:
    def __init__(self, seconds: float) -> None:
        self.deadline = monotonic() + seconds

    def remaining(self) -> float:
        return max(0.0, self.deadline - monotonic())

    def call(self, operation: Callable[[str, float], object], url: str) -> object:
        remaining = self.remaining()
        if remaining <= 0:
            raise _BudgetExhausted
        try:
            result = operation(url, remaining)
        except Exception as exc:
            if self.remaining() <= 0:
                raise _BudgetExhausted from exc
            raise
        if self.remaining() <= 0:
            raise _BudgetExhausted
        return result


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        href = dict(attrs).get("href")
        if href:
            self.links.append(html.unescape(href))


class RegistryReport:
    """Entry-level registry results; one bad tenant never hides its siblings."""

    def __init__(self) -> None:
        self.valid: list[dict[str, object]] = []
        self.invalid: list[dict[str, object]] = []
        self.stale: list[dict[str, object]] = []
        self.disabled: list[dict[str, object]] = []

    def source_queries(self) -> dict[str, list[dict[str, str]]]:
        """Return adapter-shaped queries for enabled, fresh tenants only."""
        queries: dict[str, list[dict[str, str]]] = {}
        for tenant in self.valid:
            source = str(tenant["source"])
            identifiers = tenant["identifiers"]
            assert isinstance(identifiers, dict)
            query = {str(key): str(value) for key, value in identifiers.items()}
            query["company"] = str(tenant["company"])
            query["source_tenant"] = tenant_label(tenant)
            queries.setdefault(source, []).append(query)
        return queries


def tenant_label(tenant: dict[str, object]) -> str:
    """Return the public tenant identifier used for row provenance and logs."""
    source = str(tenant["source"])
    identifiers = tenant["identifiers"]
    assert isinstance(identifiers, dict)
    if source == "comeet":
        return f"{identifiers['slug']}/{identifiers['company_uid']}"
    if source == "greenhouse" and identifiers.get("region"):
        return f"{identifiers['region']}:{identifiers['board']}"
    key = "board" if source == "greenhouse" else "account"
    return str(identifiers[key])


def _tenant_key(tenant: dict[str, object]) -> tuple[str, tuple[tuple[str, str], ...]]:
    identifiers = tenant["identifiers"]
    assert isinstance(identifiers, dict)
    return (
        str(tenant["source"]),
        tuple(sorted((str(key), str(value)) for key, value in identifiers.items())),
    )


def _merge_candidate_provenance(
    candidate: dict[str, object], provenance: object
) -> None:
    existing = candidate["provenance"]
    assert isinstance(existing, list)
    if not isinstance(provenance, list):
        return
    for evidence in provenance:
        if evidence not in existing:
            existing.append(evidence)


def _issue(index: int, entry: object, status: str, reason: str) -> dict[str, object]:
    source = entry.get("source", "unknown") if isinstance(entry, dict) else "unknown"
    company = entry.get("company", "unknown") if isinstance(entry, dict) else "unknown"
    return {
        "index": index,
        "source": str(source),
        "company": str(company),
        "status": status,
        "reason": reason,
    }


def _parse_verified_date(value: object) -> date | None:
    if not isinstance(value, str) or not value.strip():
        return None
    normalized = value.strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized).date()
    except ValueError:
        try:
            return date.fromisoformat(normalized)
        except ValueError:
            return None


def _expected_careers_url(source: str, identifiers: dict[str, object]) -> str:
    if source == "comeet":
        return (
            f"https://www.comeet.com/jobs/{identifiers.get('slug', '')}/"
            f"{identifiers.get('company_uid', '')}"
        )
    if source == "greenhouse":
        host = (
            "job-boards.eu.greenhouse.io"
            if identifiers.get("region") == "eu"
            else "job-boards.greenhouse.io"
        )
        return f"https://{host}/{identifiers.get('board', '')}"
    if source == "lever":
        return f"https://jobs.lever.co/{identifiers.get('account', '')}"
    return f"https://apply.workable.com/{identifiers.get('account', '')}/"


def _validate_entry(entry: object, as_of: date) -> tuple[list[str], date | None]:
    if not isinstance(entry, dict):
        return ["entry must be an object"], None

    errors: list[str] = []
    unexpected_fields = sorted(set(entry) - ENTRY_FIELDS)
    if unexpected_fields:
        errors.append("unexpected entry field(s): " + ", ".join(unexpected_fields))
    source_value = entry.get("source")
    source = (
        source_value
        if isinstance(source_value, str) and source_value in IDENTIFIER_FIELDS
        else None
    )
    if source is None:
        errors.append("unsupported source")

    company = entry.get("company")
    if not isinstance(company, str) or not company.strip():
        errors.append("company must be a non-empty string")

    if not isinstance(entry.get("enabled"), bool):
        errors.append("enabled must be a boolean")

    identifiers = entry.get("identifiers")
    if not isinstance(identifiers, dict):
        errors.append("identifiers must be an object")
    elif source is not None:
        required, optional = IDENTIFIER_FIELDS[source]
        allowed = set(required) | set(optional)
        missing = [key for key in required if not identifiers.get(key)]
        unexpected = sorted(set(identifiers) - allowed)
        if missing:
            errors.append("missing tenant identifier(s): " + ", ".join(missing))
        if unexpected:
            errors.append("unexpected identifier field(s): " + ", ".join(unexpected))
        for key, value in identifiers.items():
            if not isinstance(value, str) or not IDENTIFIER_RE.fullmatch(value):
                errors.append(f"invalid public identifier: {key}")

    provenance = entry.get("provenance")
    if not isinstance(provenance, list) or not provenance:
        errors.append("provenance must be a non-empty list")
    elif any(
        not isinstance(item, dict)
        or not isinstance(item.get("kind"), str)
        or not item["kind"].strip()
        or not isinstance(item.get("reference"), str)
        or not item["reference"].strip()
        for item in provenance
    ):
        errors.append("each provenance item needs non-empty kind and reference")

    verified_date = _parse_verified_date(entry.get("last_verified_at"))
    if verified_date is None:
        errors.append("last_verified_at must be an ISO date or timestamp")
    elif verified_date > as_of:
        errors.append("last_verified_at cannot be in the future")

    careers_url = entry.get("careers_url")
    parsed = None
    if isinstance(careers_url, str):
        try:
            parsed = urlparse(careers_url)
        except ValueError:
            pass
    if (
        parsed is None
        or parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        errors.append("careers_url must be a canonical public HTTPS URL")
    elif source is not None and parsed.hostname.lower() not in CAREERS_HOSTS[source]:
        errors.append("careers_url host does not match source")
    elif (
        source is not None
        and isinstance(identifiers, dict)
        and careers_url != _expected_careers_url(source, identifiers)
    ):
        errors.append("careers_url does not match tenant identifiers")

    return errors, verified_date


def load_registry(
    path: Path = REGISTRY_PATH,
    *,
    as_of: date | None = None,
    max_age_days: int = DEFAULT_MAX_AGE_DAYS,
) -> RegistryReport:
    """Load one registry and classify every tenant without cross-entry failure."""
    if max_age_days < 0:
        raise ValueError("max_age_days must be non-negative")
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise ValueError("registry schema_version must be 1")
    tenants = payload.get("tenants")
    if not isinstance(tenants, list):
        raise ValueError("registry tenants must be a list")

    today = as_of or datetime.now(timezone.utc).date()
    report = RegistryReport()
    seen_tenants: set[tuple[str, tuple[tuple[str, str], ...]]] = set()
    for index, entry in enumerate(tenants):
        errors, verified_date = _validate_entry(entry, today)
        if errors:
            report.invalid.append(_issue(index, entry, "invalid", "; ".join(errors)))
            continue
        assert isinstance(entry, dict) and verified_date is not None
        identifiers = entry["identifiers"]
        assert isinstance(identifiers, dict)
        tenant_key = (
            str(entry["source"]),
            tuple(sorted((str(key), str(value)) for key, value in identifiers.items())),
        )
        if tenant_key in seen_tenants:
            report.invalid.append(
                _issue(index, entry, "invalid", "duplicate tenant identifiers")
            )
            continue
        seen_tenants.add(tenant_key)
        if not entry["enabled"]:
            report.disabled.append(_issue(index, entry, "disabled", "disabled by registry"))
        elif (today - verified_date).days > max_age_days:
            report.stale.append(
                _issue(
                    index,
                    entry,
                    "stale",
                    f"last verified {(today - verified_date).days} days ago",
                )
            )
        else:
            report.valid.append(entry)
    return report


def _safe_url(url: str) -> str:
    """Keep only a public origin; redirect paths can contain private tokens."""
    try:
        parsed = urlparse(url)
        hostname = parsed.hostname
        port_value = parsed.port
    except (UnicodeError, ValueError):
        return ""
    if parsed.scheme not in {"http", "https"} or not hostname:
        return ""
    port = f":{port_value}" if port_value else ""
    return urlunparse((parsed.scheme, f"{hostname}{port}", "/", "", "", ""))


def _safe_https_parts(url: str) -> tuple[object, str] | None:
    if not isinstance(url, str) or any(ord(char) < 32 for char in url):
        return None
    try:
        parsed = urlparse(url)
        hostname = parsed.hostname
        port = parsed.port
    except (UnicodeError, ValueError):
        return None
    if (
        parsed.scheme != "https"
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
        or port not in (None, 443)
        or "%" in hostname
        or any(char.isspace() for char in hostname)
    ):
        return None
    try:
        normalized_host = hostname.rstrip(".").encode("idna").decode("ascii").lower()
    except UnicodeError:
        return None
    if not normalized_host:
        return None
    return parsed, normalized_host


def _validate_public_https_url(url: str) -> None:
    safe_parts = _safe_https_parts(url)
    if safe_parts is None:
        raise UnsafeEgressError("network URL must be public HTTPS on port 443")
    _, hostname = safe_parts
    try:
        answers = getaddrinfo(hostname, 443, type=SOCK_STREAM)
    except (OSError, UnicodeError) as exc:
        raise UnsafeEgressError("network hostname could not be safely resolved") from exc
    if not answers:
        raise UnsafeEgressError("network hostname returned no addresses")
    for answer in answers:
        try:
            resolved = str(answer[4][0]).split("%", 1)[0]
            address = ipaddress.ip_address(resolved)
        except (IndexError, TypeError, ValueError) as exc:
            raise UnsafeEgressError("network hostname returned an invalid address") from exc
        mapped = getattr(address, "ipv4_mapped", None)
        public_address = mapped if mapped is not None else address
        in_non_public_fixup = any(
            public_address in network
            for network in IANA_NON_PUBLIC_FIXUPS[public_address.version]
        ) and not any(
            public_address in network
            for network in IANA_PUBLIC_EXCEPTIONS[public_address.version]
        )
        if (
            in_non_public_fixup
            or not public_address.is_global
            or public_address.is_private
            or public_address.is_loopback
            or public_address.is_link_local
            or public_address.is_unspecified
            or public_address.is_reserved
            or public_address.is_multicast
        ):
            raise UnsafeEgressError("network hostname returned a non-public address")


class _PublicHTTPSRedirectHandler(HTTPRedirectHandler):
    def redirect_request(
        self,
        request: Request,
        file_pointer: object,
        code: int,
        message: str,
        headers: object,
        new_url: str,
    ) -> Request | None:
        absolute_url = urljoin(request.full_url, new_url)
        _validate_public_https_url(absolute_url)
        return super().redirect_request(
            request, file_pointer, code, message, headers, absolute_url
        )


def _open_public_https(url: str, timeout_seconds: float):
    _validate_public_https_url(url)
    request = Request(url, headers={"User-Agent": "job-radar-coach-registry/1.0"})
    response = build_opener(_PublicHTTPSRedirectHandler()).open(
        request, timeout=timeout_seconds
    )
    try:
        _validate_public_https_url(response.geturl())
    except Exception:
        response.close()
        raise
    return response


def detect_supported_ats(url: str) -> dict[str, object] | None:
    """Derive a registry-shaped ATS tenant only from an observed public URL."""
    safe_parts = _safe_https_parts(url)
    if safe_parts is None:
        return None
    parsed, host = safe_parts
    segments = [unquote(segment) for segment in parsed.path.split("/") if segment]

    if host in CAREERS_HOSTS["comeet"] and len(segments) >= 3 and segments[0] == "jobs":
        slug, company_uid = segments[1:3]
        if IDENTIFIER_RE.fullmatch(slug) and IDENTIFIER_RE.fullmatch(company_uid):
            return {
                "source": "comeet",
                "identifiers": {"slug": slug, "company_uid": company_uid},
                "careers_url": f"https://www.comeet.com/jobs/{slug}/{company_uid}",
            }

    greenhouse_board = ""
    greenhouse_region = "eu" if ".eu.greenhouse.io" in host else ""
    if host in CAREERS_HOSTS["greenhouse"] and segments:
        greenhouse_board = segments[0]
    elif host in {"boards-api.greenhouse.io", "boards-api.eu.greenhouse.io"}:
        if len(segments) >= 3 and segments[:2] == ["v1", "boards"]:
            greenhouse_board = segments[2]
            greenhouse_region = "eu" if host.startswith("boards-api.eu.") else ""
    if greenhouse_board and IDENTIFIER_RE.fullmatch(greenhouse_board):
        identifiers = {"board": greenhouse_board}
        canonical_host = "job-boards.greenhouse.io"
        if greenhouse_region:
            identifiers["region"] = greenhouse_region
            canonical_host = "job-boards.eu.greenhouse.io"
        return {
            "source": "greenhouse",
            "identifiers": identifiers,
            "careers_url": f"https://{canonical_host}/{greenhouse_board}",
        }

    lever_account = ""
    if host == "jobs.lever.co" and segments:
        lever_account = segments[0]
    elif host == "api.lever.co" and len(segments) >= 3 and segments[:2] == ["v0", "postings"]:
        lever_account = segments[2]
    if lever_account and IDENTIFIER_RE.fullmatch(lever_account):
        return {
            "source": "lever",
            "identifiers": {"account": lever_account},
            "careers_url": f"https://jobs.lever.co/{lever_account}",
        }

    if host == "apply.workable.com" and segments and segments[0].lower() != "j":
        account = segments[0]
        if IDENTIFIER_RE.fullmatch(account):
            return {
                "source": "workable",
                "identifiers": {"account": account},
                "careers_url": f"https://apply.workable.com/{account}/",
            }
    return None


def public_endpoint(candidate: dict[str, object]) -> str:
    source = str(candidate["source"])
    identifiers = candidate["identifiers"]
    assert isinstance(identifiers, dict)
    if source == "comeet":
        return str(candidate["careers_url"])
    if source == "greenhouse":
        return (
            "https://boards-api.greenhouse.io/v1/boards/"
            f"{identifiers['board']}/jobs?content=true"
        )
    if source == "lever":
        return f"https://api.lever.co/v0/postings/{identifiers['account']}?mode=json"
    return f"https://apply.workable.com/{identifiers['account']}/jobs.md"


def _endpoint_payload_is_valid(source: str, body: str | None) -> bool:
    if body is None:
        return False
    if source == "comeet":
        return re.search(r"COMPANY_POSITIONS_DATA\s*=\s*\[", body) is not None
    if source == "greenhouse":
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            return False
        return isinstance(payload, dict) and isinstance(payload.get("jobs"), list)
    if source == "lever":
        try:
            return isinstance(json.loads(body), list)
        except json.JSONDecodeError:
            return False
    lines = [line.strip() for line in body.splitlines()]
    heading_index = next(
        (index for index, line in enumerate(lines) if WORKABLE_HEADING_RE.fullmatch(line)),
        None,
    )
    if heading_index is None:
        return False
    table_index = next(
        (
            index
            for index, line in enumerate(lines[heading_index + 1 :], heading_index + 1)
            if WORKABLE_TABLE_HEADER_RE.fullmatch(line)
        ),
        None,
    )
    if (
        table_index is None
        or table_index + 1 >= len(lines)
        or WORKABLE_TABLE_SEPARATOR_RE.fullmatch(lines[table_index + 1]) is None
    ):
        return False
    return any(line == WORKABLE_FOOTER for line in lines[table_index + 2 :])


def _default_resolve_url(url: str, timeout_seconds: float) -> str:
    timeout = min(RESOLVE_TIMEOUT_SECONDS, timeout_seconds)
    with _open_public_https(url, timeout) as response:
        return response.geturl()


def _default_fetcher(url: str, timeout_seconds: float) -> str | None:
    timeout = min(FETCH_TIMEOUT_SECONDS, timeout_seconds)
    with _open_public_https(url, timeout) as response:
        return response.read().decode("utf-8", errors="replace")


def _company_from_markdown(line: str, fallback: str) -> str:
    bold = re.search(r"\*\*([^*]+)\*\*", line)
    if bold:
        value = re.split(r"\s+[—–-]\s+", bold.group(1), maxsplit=1)[0].strip()
        if value:
            return value
    return fallback


def _corpus_links(
    career_hub_path: Path | None, shushu_csv_path: Path | None
) -> list[dict[str, object]]:
    links: list[dict[str, object]] = []
    if career_hub_path is not None:
        path = Path(career_hub_path)
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            urls = MARKDOWN_LINK_RE.findall(line)
            if not urls:
                urls = RAW_URL_RE.findall(line)
            for url in dict.fromkeys(urls):
                detected = detect_supported_ats(url)
                fallback = "unknown"
                if detected is not None:
                    fallback = tenant_label({**detected, "company": "unknown"})
                links.append(
                    {
                        "company": _company_from_markdown(line, fallback),
                        "url": url,
                        "provenance": [
                            {
                                "kind": "career-hub",
                                "reference": f"{path.name}:line-{line_number}",
                            }
                        ],
                    }
                )

    if shushu_csv_path is not None:
        path = Path(shushu_csv_path)
        with path.open(encoding="utf-8-sig", newline="") as handle:
            for row_number, row in enumerate(csv.DictReader(handle), 2):
                formula = str(row.get("Company", ""))
                match = HYPERLINK_RE.fullmatch(formula)
                if match is None:
                    if formula.strip():
                        links.append(
                            {
                                "company": formula.strip(),
                                "url": "",
                                "provenance": [
                                    {
                                        "kind": "shushu-csv",
                                        "reference": f"{path.name}:row-{row_number}",
                                    }
                                ],
                            }
                        )
                    continue
                url, company = match.groups()
                links.append(
                    {
                        "company": company.strip() or "unknown",
                        "url": url,
                        "provenance": [
                            {
                                "kind": "shushu-csv",
                                "reference": f"{path.name}:row-{row_number}",
                            }
                        ],
                    }
                )
    return links


def _page_supported_urls(page_url: str, body: str | None) -> list[str]:
    if not body:
        return []
    parser = _LinkParser()
    parser.feed(body)
    urls: list[str] = []
    for href in parser.links:
        try:
            absolute = urljoin(page_url, href)
        except ValueError:
            continue
        if absolute and detect_supported_ats(absolute):
            urls.append(absolute)
    return urls


def _page_career_urls(page_url: str, body: str | None) -> list[str]:
    if not body:
        return []
    parser = _LinkParser()
    parser.feed(body)
    page_parts = _safe_https_parts(page_url)
    if page_parts is None:
        return []
    _, page_host = page_parts
    page_origin = ("https", page_host, 443)
    urls: list[str] = []
    for href in parser.links:
        try:
            absolute = urljoin(page_url, href)
        except ValueError:
            continue
        link_parts = _safe_https_parts(absolute)
        if link_parts is None:
            continue
        parsed, link_host = link_parts
        if (
            (parsed.scheme, link_host, parsed.port or 443) == page_origin
            and CAREER_LINK_HINT_RE.search(parsed.path)
            and absolute not in urls
        ):
            urls.append(absolute)
    return urls[:5]


def import_candidates(
    *,
    career_hub_path: Path | None = None,
    shushu_csv_path: Path | None = None,
    resolve_url: Callable[[str, float], str] = _default_resolve_url,
    fetcher: Callable[[str, float], str | None] = _default_fetcher,
    verified_at: date | None = None,
    deadline_seconds: float = 120,
) -> list[dict[str, object]]:
    """Read corpora and emit candidates without writing the registry.

    Network callbacks receive ``(url, remaining_seconds)`` and must honor that
    timeout if callers need the deadline to be a hard wall-clock bound. Custom
    callbacks are trusted seams and do not inherit the default egress checks.
    """
    if deadline_seconds < 0:
        raise ValueError("deadline_seconds must be non-negative")
    observed_on = (verified_at or datetime.now(timezone.utc).date()).isoformat()
    budget = _NetworkBudget(deadline_seconds)
    candidates: list[dict[str, object]] = []
    tenant_candidates: dict[
        tuple[str, tuple[tuple[str, str], ...]], dict[str, object]
    ] = {}
    for link in _corpus_links(career_hub_path, shushu_csv_path):
        company = str(link["company"])
        provenance = link["provenance"]
        input_url = str(link["url"])
        if not input_url:
            candidates.append(
                {
                    "company": company,
                    "status": "no-url",
                    "reason": "corpus row has no company URL",
                    "provenance": provenance,
                }
            )
            continue
        direct_tenant = detect_supported_ats(input_url)
        if direct_tenant is not None:
            existing_candidate = tenant_candidates.get(_tenant_key(direct_tenant))
            if existing_candidate is not None:
                _merge_candidate_provenance(existing_candidate, provenance)
                continue
        if budget.remaining() <= 0:
            candidates.append(
                {
                    "company": company,
                    "status": "budget-exhausted",
                    "reason": "candidate import deadline reached before network validation",
                    "provenance": provenance,
                }
            )
            continue
        try:
            if direct_tenant is not None:
                resolved_url = input_url
            else:
                try:
                    resolved_url = str(budget.call(resolve_url, input_url))
                except _BudgetExhausted:
                    raise
                except Exception as exc:  # candidate-level network boundary
                    candidates.append(
                        {
                            "company": company,
                            "status": "resolve-failed",
                            "reason": f"redirect resolution failed: {type(exc).__name__}",
                            "provenance": provenance,
                        }
                    )
                    continue
                if _safe_https_parts(resolved_url) is None:
                    candidates.append(
                        {
                            "company": company,
                            "status": "resolve-failed",
                            "reason": "redirect resolution returned an invalid URL",
                            "provenance": provenance,
                        }
                    )
                    continue

            detected_urls = [resolved_url] if detect_supported_ats(resolved_url) else []
            discovery_failure: tuple[str, str] | None = None
            if not detected_urls:
                try:
                    page_body = budget.call(fetcher, resolved_url)
                except _BudgetExhausted:
                    raise
                except Exception as exc:
                    page_body = None
                    discovery_failure = (
                        "validation-failed",
                        f"resolved page request failed: {type(exc).__name__}",
                    )
                detected_urls = _page_supported_urls(resolved_url, page_body)
                if not detected_urls:
                    for career_url in _page_career_urls(resolved_url, page_body):
                        try:
                            resolved_career_url = str(budget.call(resolve_url, career_url))
                        except _BudgetExhausted:
                            raise
                        except Exception as exc:
                            if discovery_failure is None:
                                discovery_failure = (
                                    "resolve-failed",
                                    "career redirect resolution failed: "
                                    f"{type(exc).__name__}",
                                )
                            continue
                        if _safe_https_parts(resolved_career_url) is None:
                            if discovery_failure is None:
                                discovery_failure = (
                                    "resolve-failed",
                                    "career redirect returned an invalid URL",
                                )
                            continue
                        if detect_supported_ats(resolved_career_url):
                            detected_urls.append(resolved_career_url)
                            continue
                        try:
                            career_body = budget.call(fetcher, resolved_career_url)
                        except _BudgetExhausted:
                            raise
                        except Exception as exc:
                            if discovery_failure is None:
                                discovery_failure = (
                                    "validation-failed",
                                    f"career page request failed: {type(exc).__name__}",
                                )
                            continue
                        detected_urls.extend(
                            _page_supported_urls(resolved_career_url, career_body)
                        )
            if not detected_urls:
                if discovery_failure is not None:
                    status, reason = discovery_failure
                    candidates.append(
                        {
                            "company": company,
                            "status": status,
                            "reason": reason,
                            "provenance": provenance,
                        }
                    )
                    continue
                candidates.append(
                    {
                        "company": company,
                        "status": "unsupported",
                        "reason": "no supported ATS URL observed",
                        "resolved_url": _safe_url(resolved_url),
                        "provenance": provenance,
                    }
                )
                continue

            for detected_url in dict.fromkeys(detected_urls):
                detected = detect_supported_ats(detected_url)
                assert detected is not None
                tenant_key = _tenant_key(detected)
                existing_candidate = tenant_candidates.get(tenant_key)
                if existing_candidate is not None:
                    _merge_candidate_provenance(existing_candidate, provenance)
                    continue
                candidate = {
                    **detected,
                    "company": company,
                    "provenance": list(provenance),
                    "last_verified_at": observed_on,
                    "enabled": True,
                }
                try:
                    endpoint_body = budget.call(fetcher, public_endpoint(candidate))
                except _BudgetExhausted:
                    raise
                except Exception as exc:  # candidate-level network boundary
                    candidate.update(
                        status="validation-failed",
                        reason=f"public endpoint request failed: {type(exc).__name__}",
                    )
                else:
                    if _endpoint_payload_is_valid(str(candidate["source"]), endpoint_body):
                        candidate.update(status="verified", reason="public endpoint validated")
                    else:
                        candidate.update(
                            status="validation-failed",
                            reason="public endpoint returned an unexpected payload",
                        )
                candidates.append(candidate)
                tenant_candidates[tenant_key] = candidate
        except _BudgetExhausted:
            candidates.append(
                {
                    "company": company,
                    "status": "budget-exhausted",
                    "reason": "candidate import deadline reached during network validation",
                    "provenance": provenance,
                }
            )
    return candidates


def _print_registry_report(report: RegistryReport) -> None:
    groups = (
        ("VALID", report.valid),
        ("INVALID", report.invalid),
        ("STALE", report.stale),
        ("DISABLED", report.disabled),
    )
    for heading, entries in groups:
        print(f"{heading} ({len(entries)})")
        for entry in entries:
            if heading == "VALID":
                assert isinstance(entry, dict)
                print(
                    f"  {entry['source']} | {entry['company']} | "
                    f"tenant={tenant_label(entry)}"
                )
            else:
                print(
                    f"  {entry['source']} | {entry['company']} | {entry['reason']}"
                )


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="classify registry tenants")
    mode.add_argument(
        "--import-candidates",
        action="store_true",
        help="read corpora and print review candidates without writing the registry",
    )
    parser.add_argument("--registry", type=Path, default=REGISTRY_PATH)
    parser.add_argument("--as-of", type=date.fromisoformat)
    parser.add_argument("--max-age-days", type=int, default=DEFAULT_MAX_AGE_DAYS)
    parser.add_argument("--career-hub", type=Path)
    parser.add_argument("--shushu-csv", type=Path)
    parser.add_argument(
        "--deadline-seconds",
        type=float,
        default=120,
        help="stop scheduling network stages after this many seconds",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.dry_run:
        report = load_registry(
            args.registry, as_of=args.as_of, max_age_days=args.max_age_days
        )
        _print_registry_report(report)
        return 1 if report.invalid or report.stale else 0
    if args.career_hub is None and args.shushu_csv is None:
        raise SystemExit("--import-candidates needs --career-hub and/or --shushu-csv")
    candidates = import_candidates(
        career_hub_path=args.career_hub,
        shushu_csv_path=args.shushu_csv,
        verified_at=args.as_of,
        deadline_seconds=args.deadline_seconds,
    )
    print(json.dumps(candidates, indent=2, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
