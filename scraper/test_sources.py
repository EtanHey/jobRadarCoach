#!/usr/bin/env python3
"""Fixture-backed tests for round-five public ATS adapters."""

import importlib.util
import inspect
import json
import socket
import subprocess
import sys
import time
from datetime import date
from pathlib import Path

import pytest


HERE = Path(__file__).resolve().parent
HARVEST_PATH = HERE / "harvest.py"
FIXTURES = HERE / "fixtures"
SEARCHES_PATH = HERE / "searches.yaml"
REGISTRY_PATH = HERE / "source-registry.json"
REGISTRY_MODULE_PATH = HERE / "source_registry.py"
SOURCE_NAMES = ("comeet", "greenhouse", "lever", "workable")
REQUIRED_POSTING_FIELDS = {
    "id", "title", "company", "location", "url", "posted_ago", "source"
}


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_harvest():
    return load_module(HARVEST_PATH, "job_feed_harvest_round5")


def load_source(name: str):
    path = HERE / "sources" / f"{name}.py"
    assert path.is_file(), f"missing source adapter: {path}"
    return load_module(path, f"job_feed_source_{name}")


def load_source_registry():
    assert REGISTRY_MODULE_PATH.is_file(), "missing source registry loader"
    return load_module(REGISTRY_MODULE_PATH, "job_feed_source_registry")


def assert_uniform_posting(posting: dict[str, object], source: str) -> None:
    assert REQUIRED_POSTING_FIELDS <= set(posting)
    assert posting["source"] == source
    assert str(posting["id"]).startswith(f"{source}:")
    assert posting["jd_fetched"] is True
    assert posting["jd_text"]


def test_comeet_adapter_parses_real_board_fixture() -> None:
    module = load_source("comeet")
    fixture = (FIXTURES / "comeet-senai-board-2026-08-11.html").read_text(
        encoding="utf-8"
    )

    postings = module.fetch(
        {"slug": "senai", "company_uid": "CA.004"},
        fetcher=lambda _url: fixture,
        before_request=lambda: None,
    )

    assert len(postings) == 4
    assert postings[0]["id"] == "comeet:CA.004:22.26F"
    assert postings[0]["title"] == "Full-Stack Engineer"
    assert "posted_at" not in postings[0]
    assert postings[0]["updated_at"] == "2026-08-05T07:31:27Z"
    assert postings[0]["posted_ago"] == "Updated 2026-08-05 07:31 UTC"
    assert_uniform_posting(postings[0], "comeet")


def test_greenhouse_adapter_parses_real_board_fixture() -> None:
    module = load_source("greenhouse")
    fixture = (
        FIXTURES / "greenhouse-guiddelinkedin-board-2026-08-11.json"
    ).read_text(encoding="utf-8")

    postings = module.fetch(
        {"board": "guiddelinkedin"},
        fetcher=lambda _url: fixture,
        before_request=lambda: None,
    )

    assert len(postings) == 9
    assert postings[0]["id"] == "greenhouse:guiddelinkedin:4873203101"
    assert postings[0]["company"] == "Guidde"
    assert postings[0]["posted_at"] == "2026-05-28T06:59:25-04:00"
    assert postings[0]["updated_at"] == "2026-05-28T07:00:01-04:00"
    assert postings[0]["posted_ago"] == "2026-05-28 10:59 UTC"
    assert_uniform_posting(postings[0], "greenhouse")


def test_lever_adapter_parses_real_board_fixture() -> None:
    module = load_source("lever")
    fixture = (FIXTURES / "lever-zadara-board-2026-08-11.json").read_text(
        encoding="utf-8"
    )

    postings = module.fetch(
        {"account": "Zadara", "company": "Zadara"},
        fetcher=lambda _url: fixture,
        before_request=lambda: None,
    )

    assert len(postings) == 7
    assert postings[0]["id"] == (
        "lever:Zadara:47a519ee-d580-4c1c-bf46-2b2955ef81a1"
    )
    assert postings[0]["posted_at"] == "2026-04-29T16:11:26.336000Z"
    assert postings[0]["posted_ago"] == "2026-04-29 16:11 UTC"
    assert_uniform_posting(postings[0], "lever")


@pytest.mark.parametrize(
    ("source", "query", "body", "expected_ids"),
    [
        (
            "comeet",
            {"slug": "acme", "company_uid": "CA.001"},
            "<script>COMPANY_POSITIONS_DATA = "
            + json.dumps(
                [
                    {"uid": "good-1", "name": "Software Engineer", "time_updated": "2026-08-11T08:00:00Z"},
                    {"uid": "bad", "name": "Software Engineer", "time_updated": None},
                    {"uid": "good-2", "name": "Backend Engineer", "time_updated": "2026-08-11T09:00:00Z"},
                ]
            )
            + "; POSITION_DATA = {};</script>",
            ["comeet:CA.001:good-1", "comeet:CA.001:bad", "comeet:CA.001:good-2"],
        ),
        (
            "greenhouse",
            {"board": "acme", "company": "Acme"},
            json.dumps(
                {
                    "jobs": [
                        {"id": 1, "title": "Software Engineer", "first_published": "2026-08-11T08:00:00Z"},
                        {"id": 2, "title": "Software Engineer", "first_published": None},
                        {"id": 3, "title": "Backend Engineer", "first_published": "2026-08-11T09:00:00Z"},
                    ]
                }
            ),
            ["greenhouse:acme:1", "greenhouse:acme:2", "greenhouse:acme:3"],
        ),
        (
            "lever",
            {"account": "acme", "company": "Acme"},
            json.dumps(
                [
                    {"id": "good-1", "text": "Software Engineer", "createdAt": 1786435200000},
                    {"id": "bad", "text": "Software Engineer", "createdAt": None},
                    {"id": "good-2", "text": "Backend Engineer", "createdAt": 1786438800000},
                ]
            ),
            ["lever:acme:good-1", "lever:acme:bad", "lever:acme:good-2"],
        ),
    ],
)
def test_unparseable_timestamp_keeps_the_board_row_without_display_metadata(
    source: str,
    query: dict[str, str],
    body: str,
    expected_ids: list[str],
) -> None:
    module = load_source(source)

    postings = module.fetch(
        query,
        fetcher=lambda _url: body,
        before_request=lambda: None,
    )

    assert [posting["id"] for posting in postings] == expected_ids
    bad = next(posting for posting in postings if posting["posted_ago"] == "")
    assert bad["posted_ago"] == ""


def test_workable_adapter_fetches_real_markdown_board_and_jd_fixture() -> None:
    module = load_source("workable")
    board = (FIXTURES / "workable-myteam-jobs-2026-08-11.md").read_text(
        encoding="utf-8"
    )
    detail = (
        FIXTURES / "workable-myteam-job-99FDF530F1-2026-08-11.md"
    ).read_text(encoding="utf-8")
    header = "\n".join(board.splitlines()[:6])
    target_row = next(line for line in board.splitlines() if "99FDF530F1" in line)
    one_job_board = f"{header}\n{target_row}\n"
    requested: list[str] = []

    def fetcher(url: str) -> str:
        requested.append(url)
        return detail if "/jobs/view/" in url else one_job_board

    postings = module.fetch(
        {"account": "myteam", "company": "my team"},
        fetcher=fetcher,
        before_request=lambda: None,
    )

    assert len(postings) == 1
    assert postings[0]["id"] == "workable:myteam:99FDF530F1"
    assert postings[0]["posted_at"] == "2024-09-08T00:00:00Z"
    assert postings[0]["posted_ago"] == "2024-09-08"
    assert "posted_precision" not in postings[0]
    assert requested == [
        "https://apply.workable.com/myteam/jobs.md",
        "https://apply.workable.com/myteam/jobs/view/99FDF530F1.md",
    ]
    assert_uniform_posting(postings[0], "workable")


def test_ats_filter_api_has_no_dead_harvested_at_parameter() -> None:
    harvest = load_harvest()

    assert "harvested_at" not in inspect.signature(
        harvest._source_posting_matches
    ).parameters
    assert "harvested_at" not in inspect.signature(
        harvest.filter_source_postings
    ).parameters


def test_source_registry_is_checked_in_and_separate_from_linkedin_searches() -> None:
    harvest = load_harvest()
    registry_module = load_source_registry()
    config = json.loads(SEARCHES_PATH.read_text(encoding="utf-8"))

    assert [search["keywords"] for search in harvest.load_searches(SEARCHES_PATH)] == [
        "Software Engineer",
        "Full Stack Engineer",
        "Frontend Engineer",
        "Backend Engineer",
        "Product Engineer",
        "Platform Engineer",
        "AI Engineer",
        "Machine Learning Engineer",
        "Site Reliability Engineer",
        "Engineering Manager",
    ]
    assert "sources" not in config

    registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    assert registry["schema_version"] == 1
    assert len(registry["tenants"]) >= len(SOURCE_NAMES)
    required = {
        "source",
        "identifiers",
        "company",
        "careers_url",
        "provenance",
        "last_verified_at",
        "enabled",
    }
    assert all(required <= set(entry) for entry in registry["tenants"])
    report = registry_module.load_registry(REGISTRY_PATH, as_of=date(2026, 8, 26))
    assert report.invalid == []
    assert report.stale == []
    assert len(report.valid) == sum(entry["enabled"] for entry in registry["tenants"])
    assert set(report.source_queries()) == set(SOURCE_NAMES)
    assert all(
        query["company"] and query["source_tenant"]
        for queries in report.source_queries().values()
        for query in queries
    )


def test_registry_loader_isolates_malformed_and_stale_siblings(
    tmp_path: Path, monkeypatch
) -> None:
    registry_module = load_source_registry()
    harvest = load_harvest()

    def entry(
        board: str,
        company: str,
        *,
        last_verified_at: str = "2026-08-20",
    ) -> dict[str, object]:
        return {
            "source": "greenhouse",
            "identifiers": {"board": board},
            "company": company,
            "careers_url": f"https://job-boards.greenhouse.io/{board}",
            "provenance": [
                {"kind": "test-fixture", "reference": f"fixture:{board}"}
            ],
            "last_verified_at": last_verified_at,
            "enabled": True,
        }

    malformed = entry("bad", "Malformed")
    malformed["identifiers"] = {}
    stale = {
        **entry("old", "Stale", last_verified_at="2026-01-01"),
        "source": "lever",
        "identifiers": {"account": "old"},
        "careers_url": "https://jobs.lever.co/old",
    }
    registry_path = tmp_path / "registry.json"
    registry_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "tenants": [
                    entry("good-one", "Good One"),
                    malformed,
                    stale,
                    entry("good-two", "Good Two"),
                ],
            }
        ),
        encoding="utf-8",
    )

    report = registry_module.load_registry(
        registry_path, as_of=date(2026, 8, 26), max_age_days=30
    )

    assert [tenant["company"] for tenant in report.valid] == [
        "Good One",
        "Good Two",
    ]
    assert [(issue["company"], issue["status"]) for issue in report.invalid] == [
        ("Malformed", "invalid")
    ]
    assert [(issue["company"], issue["status"]) for issue in report.stale] == [
        ("Stale", "stale")
    ]

    calls: list[str] = []

    class Greenhouse:
        @staticmethod
        def fetch(query, **_kwargs):
            calls.append(query["board"])
            return [{"id": f"greenhouse:{query['board']}:1", "source": "greenhouse"}]

    monkeypatch.setattr(harvest, "load_source_adapter", lambda _name: Greenhouse)
    postings, warnings = harvest.harvest_sources(
        report.source_queries(),
        {"greenhouse"},
        fetcher=lambda _url: None,
        before_request=lambda: None,
    )

    assert calls == ["good-one", "good-two"]
    assert [posting["id"] for posting in postings] == [
        "greenhouse:good-one:1",
        "greenhouse:good-two:1",
    ]
    assert warnings == 0


def test_candidate_importer_is_read_only_and_emits_reviewable_validation(
    tmp_path: Path
) -> None:
    registry_module = load_source_registry()
    assert hasattr(registry_module, "import_candidates"), "missing candidate importer"

    career_hub = tmp_path / "Career Hub.md"
    career_hub.write_text(
        "| **Acme — Backend Engineer** | "
        "[apply](https://jobs.lever.co/acme/role-1?source=private-tracker) |\n",
        encoding="utf-8",
    )
    shushu = tmp_path / "shushu.csv"
    shushu.write_text(
        "Company,Role\n"
        '"=HYPERLINK(""https://redirect.test/beta-token"",""Beta"")",Full Stack\n'
        '"=HYPERLINK(""https://redirect.test/gamma-token"",""Gamma"")",Backend\n'
        '"=HYPERLINK(""https://redirect.test/no-ats-token"",""No ATS"")",Frontend\n'
        "PlainCo,Backend\n",
        encoding="utf-8",
    )
    registry_before = REGISTRY_PATH.read_bytes()
    resolved = {
        "https://redirect.test/beta-token": "https://beta.example/careers",
        "https://redirect.test/gamma-token": "https://gamma.example/",
        "https://gamma.example/careers": "https://gamma.example/careers",
        "https://redirect.test/no-ats-token": (
            "https://no-ats.example/jobs/no-ats-token"
        ),
    }
    bodies = {
        "https://api.lever.co/v0/postings/acme?mode=json": "[]",
        "https://beta.example/careers": (
            '<a href="https://job-boards.eu.greenhouse.io/beta/jobs/123">Apply</a>'
        ),
        "https://boards-api.greenhouse.io/v1/boards/beta/jobs?content=true": (
            '{"jobs": []}'
        ),
        "https://gamma.example/": '<a href="/careers">Careers</a>',
        "https://gamma.example/careers": (
            '<a href="https://jobs.lever.co/gamma">Open roles</a>'
        ),
        "https://api.lever.co/v0/postings/gamma?mode=json": "[]",
        "https://no-ats.example/jobs/no-ats-token": "<p>Send us an email.</p>",
    }

    def resolver(url: str, _timeout_seconds: float) -> str:
        if url.startswith("https://jobs.lever.co/acme"):
            raise AssertionError("direct ATS URLs do not need redirect resolution")
        return resolved.get(url, url)

    def fetcher(url: str, _timeout_seconds: float) -> str | None:
        return bodies.get(url)

    candidates = registry_module.import_candidates(
        career_hub_path=career_hub,
        shushu_csv_path=shushu,
        resolve_url=resolver,
        fetcher=fetcher,
        verified_at=date(2026, 8, 26),
    )

    verified = [candidate for candidate in candidates if candidate["status"] == "verified"]
    unsupported = [
        candidate for candidate in candidates if candidate["status"] == "unsupported"
    ]
    no_url = [candidate for candidate in candidates if candidate["status"] == "no-url"]
    assert [candidate["company"] for candidate in verified] == [
        "Acme",
        "Beta",
        "Gamma",
    ]
    assert verified[0]["source"] == "lever"
    assert verified[0]["identifiers"] == {"account": "acme"}
    assert verified[0]["careers_url"] == "https://jobs.lever.co/acme"
    assert verified[1]["source"] == "greenhouse"
    assert verified[1]["identifiers"] == {"board": "beta", "region": "eu"}
    assert verified[1]["last_verified_at"] == "2026-08-26"
    assert verified[2]["identifiers"] == {"account": "gamma"}
    assert [candidate["company"] for candidate in unsupported] == ["No ATS"]
    assert [candidate["company"] for candidate in no_url] == ["PlainCo"]
    assert all("private-tracker" not in json.dumps(candidate) for candidate in candidates)
    assert all("token" not in json.dumps(candidate) for candidate in candidates)
    assert REGISTRY_PATH.read_bytes() == registry_before


def test_greenhouse_eu_board_uses_the_shared_public_api_host() -> None:
    registry_module = load_source_registry()
    candidate = registry_module.detect_supported_ats(
        "https://job-boards.eu.greenhouse.io/wedev/jobs/4871703101"
    )

    assert candidate is not None
    assert candidate["identifiers"] == {"board": "wedev", "region": "eu"}
    assert registry_module.public_endpoint(candidate) == (
        "https://boards-api.greenhouse.io/v1/boards/wedev/jobs?content=true"
    )


@pytest.mark.parametrize(
    "url",
    [
        "file://jobs.lever.co/acme",
        "http://jobs.lever.co/acme",
        "ftp://jobs.lever.co/acme",
        "data://jobs.lever.co/acme",
        "https://user:secret@jobs.lever.co/acme",
        "https://jobs.lever.co:444/acme",
        "https://jobs.lever.co:not-a-port/acme",
        "https://[invalid/acme",
    ],
)
def test_ats_detection_rejects_unsafe_url_shapes(url: str) -> None:
    registry_module = load_source_registry()

    assert registry_module.detect_supported_ats(url) is None


def test_ats_detection_preserves_query_bearing_canonical_link() -> None:
    registry_module = load_source_registry()

    candidate = registry_module.detect_supported_ats(
        "https://jobs.lever.co/acme/role-1?source=private-token"
    )

    assert candidate is not None
    assert candidate["identifiers"] == {"account": "acme"}
    assert candidate["careers_url"] == "https://jobs.lever.co/acme"


@pytest.mark.parametrize(
    ("hostname", "answers"),
    [
        ("loopback.test", ("127.0.0.1",)),
        ("private.test", ("10.0.0.1",)),
        ("metadata.test", ("169.254.169.254",)),
        ("unspecified.test", ("0.0.0.0",)),
        ("multicast.test", ("224.0.0.1",)),
        ("reserved.test", ("240.0.0.1",)),
        ("non-public.test", ("100.64.0.1",)),
        ("ipv6-loopback.test", ("::1",)),
        ("ipv6-private.test", ("fc00::1",)),
        ("ipv6-link-local.test", ("fe80::1",)),
        ("ipv6-multicast.test", ("ff02::1",)),
        ("ipv6-unspecified.test", ("::",)),
        ("mapped-loopback.test", ("::ffff:127.0.0.1",)),
        ("mapped-private.test", ("::ffff:192.168.0.1",)),
        ("127.1", ("127.0.0.1",)),
        ("2130706433", ("127.0.0.1",)),
        ("0x7f000001", ("127.0.0.1",)),
        ("017700000001", ("127.0.0.1",)),
        ("mixed.test", ("93.184.216.34", "10.0.0.1")),
    ],
)
def test_public_https_validator_rejects_any_non_public_dns_answer(
    monkeypatch, hostname: str, answers: tuple[str, ...]
) -> None:
    registry_module = load_source_registry()

    def fake_getaddrinfo(
        requested_host: str, port: int, *_args: object, **_kwargs: object
    ) -> list[tuple[object, ...]]:
        assert requested_host == hostname
        assert port == 443
        return [
            (
                socket.AF_INET6 if ":" in address else socket.AF_INET,
                socket.SOCK_STREAM,
                socket.IPPROTO_TCP,
                "",
                (address, port, 0, 0) if ":" in address else (address, port),
            )
            for address in answers
        ]

    monkeypatch.setattr(
        registry_module, "getaddrinfo", fake_getaddrinfo, raising=False
    )

    with pytest.raises(ValueError):
        registry_module._validate_public_https_url(f"https://{hostname}/careers")


def test_public_https_validator_accepts_only_public_dns_answers(monkeypatch) -> None:
    registry_module = load_source_registry()

    def fake_getaddrinfo(
        _host: str, port: int, *_args: object, **_kwargs: object
    ) -> list[tuple[object, ...]]:
        return [
            (
                socket.AF_INET,
                socket.SOCK_STREAM,
                socket.IPPROTO_TCP,
                "",
                ("93.184.216.34", port),
            ),
            (
                socket.AF_INET6,
                socket.SOCK_STREAM,
                socket.IPPROTO_TCP,
                "",
                ("2606:2800:220:1:248:1893:25c8:1946", port, 0, 0),
            ),
        ]

    monkeypatch.setattr(
        registry_module, "getaddrinfo", fake_getaddrinfo, raising=False
    )

    registry_module._validate_public_https_url("https://example.test/path?query=kept")


def test_system_python_rejects_iana_non_public_dns_ranges() -> None:
    script = """
import runpy
import socket
import sys

module = runpy.run_path(sys.argv[1])

def resolve_to(address):
    family = socket.AF_INET6 if ":" in address else socket.AF_INET
    module["_validate_public_https_url"].__globals__["getaddrinfo"] = (
        lambda _host, port, **_kwargs: [
            (
                family,
                socket.SOCK_STREAM,
                socket.IPPROTO_TCP,
                "",
                (address, port, 0, 0) if family == socket.AF_INET6 else (address, port),
            )
        ]
    )

for address in ("192.0.0.8", "192.88.99.2", "2002::1", "3fff::1"):
    resolve_to(address)
    try:
        module["_validate_public_https_url"]("https://example.test/careers")
    except module["UnsafeEgressError"]:
        continue
    raise SystemExit("accepted IANA non-public DNS address: " + address)

for address in ("192.0.0.9", "192.0.0.10"):
    resolve_to(address)
    try:
        module["_validate_public_https_url"]("https://example.test/careers")
    except module["UnsafeEgressError"] as error:
        raise SystemExit("rejected IANA public DNS address: " + address) from error
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(REGISTRY_MODULE_PATH)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("helper_name", ["_default_resolve_url", "_default_fetcher"])
@pytest.mark.parametrize(
    "url",
    [
        "file:///dev/null",
        "http://93.184.216.34/",
        "ftp://93.184.216.34/",
        "data:text/plain,hello",
        "https://127.0.0.1/",
        "https://user:secret@example.test/",
        "https://example.test:444/",
        "https://[fe80::1%25en0]/",
    ],
)
def test_default_network_helpers_reject_unsafe_target_before_open(
    monkeypatch, helper_name: str, url: str
) -> None:
    registry_module = load_source_registry()
    opened: list[str] = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def geturl(self) -> str:
            return url

        def read(self) -> bytes:
            return b""

    def fake_open(request, **_kwargs: object):
        opened.append(request.full_url)
        return Response()

    class Opener:
        open = staticmethod(fake_open)

    monkeypatch.setattr(registry_module, "urlopen", fake_open, raising=False)
    monkeypatch.setattr(
        registry_module, "build_opener", lambda *_handlers: Opener(), raising=False
    )

    with pytest.raises(ValueError):
        getattr(registry_module, helper_name)(url, 1.0)

    assert opened == []


@pytest.mark.parametrize(
    "redirect_url",
    [
        "http://public.example/next",
        "https://127.0.0.1/private",
        "https://user:secret@public.example/next",
        "https://public.example:444/next",
    ],
)
def test_redirect_handler_blocks_unsafe_target_before_follow(
    monkeypatch, redirect_url: str
) -> None:
    registry_module = load_source_registry()

    def fake_getaddrinfo(
        host: str, port: int, *_args: object, **_kwargs: object
    ) -> list[tuple[object, ...]]:
        address = "127.0.0.1" if host == "127.0.0.1" else "93.184.216.34"
        return [
            (
                socket.AF_INET,
                socket.SOCK_STREAM,
                socket.IPPROTO_TCP,
                "",
                (address, port),
            )
        ]

    monkeypatch.setattr(
        registry_module, "getaddrinfo", fake_getaddrinfo, raising=False
    )
    handler = registry_module._PublicHTTPSRedirectHandler()
    request = registry_module.Request("https://public.example/start")

    with pytest.raises(ValueError):
        handler.redirect_request(request, None, 302, "Found", {}, redirect_url)


def test_redirect_handler_allows_public_https_target(monkeypatch) -> None:
    registry_module = load_source_registry()

    def fake_getaddrinfo(
        _host: str, port: int, *_args: object, **_kwargs: object
    ) -> list[tuple[object, ...]]:
        return [
            (
                socket.AF_INET,
                socket.SOCK_STREAM,
                socket.IPPROTO_TCP,
                "",
                ("93.184.216.34", port),
            )
        ]

    monkeypatch.setattr(
        registry_module, "getaddrinfo", fake_getaddrinfo, raising=False
    )
    handler = registry_module._PublicHTTPSRedirectHandler()
    request = registry_module.Request("https://public.example/start")

    redirected = handler.redirect_request(
        request,
        None,
        302,
        "Found",
        {},
        "https://next.example/path?source=kept",
    )

    assert redirected is not None
    assert redirected.full_url == "https://next.example/path?source=kept"


def test_nested_career_discovery_requires_exact_safe_origin() -> None:
    registry_module = load_source_registry()
    body = "".join(
        [
            '<a href="/careers">relative</a>',
            '<a href="https://EXAMPLE.test:443/jobs">explicit default port</a>',
            '<a href="http://example.test/jobs">downgrade</a>',
            '<a href="https://example.test:444/jobs">alternate port</a>',
            '<a href="https://user:secret@example.test/jobs">credentials</a>',
            '<a href="https://other.test/jobs">other host</a>',
        ]
    )

    assert registry_module._page_career_urls("https://example.test/root", body) == [
        "https://example.test/careers",
        "https://EXAMPLE.test:443/jobs",
    ]


def test_unsafe_corpus_row_isolated_without_url_or_token_leak(
    tmp_path: Path, monkeypatch
) -> None:
    registry_module = load_source_registry()
    shushu = tmp_path / "shushu.csv"
    shushu.write_text(
        "Company,Role\n"
        '"=HYPERLINK(""file:///dev/null?TOP-SECRET-TOKEN"",""Unsafe"")",Backend\n'
        '"=HYPERLINK(""https://jobs.lever.co/acme/role?source=PRIVATE-TOKEN"",""Healthy"")",Frontend\n',
        encoding="utf-8",
    )

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def geturl(self) -> str:
            return "file:///dev/null?TOP-SECRET-TOKEN"

    monkeypatch.setattr(
        registry_module, "urlopen", lambda *_args, **_kwargs: Response(), raising=False
    )

    candidates = registry_module.import_candidates(
        shushu_csv_path=shushu,
        resolve_url=registry_module._default_resolve_url,
        fetcher=lambda _url, _timeout_seconds: "[]",
        deadline_seconds=5,
    )

    assert [(candidate["company"], candidate["status"]) for candidate in candidates] == [
        ("Unsafe", "resolve-failed"),
        ("Healthy", "verified"),
    ]
    serialized = json.dumps(candidates)
    assert "file:" not in serialized
    assert "TOP-SECRET-TOKEN" not in serialized
    assert "PRIVATE-TOKEN" not in serialized


def test_workable_shortlink_is_not_a_tenant() -> None:
    registry_module = load_source_registry()

    assert (
        registry_module.detect_supported_ats(
            "https://apply.workable.com/j/ABCDEF1234?utm_source=private"
        )
        is None
    )


def test_workable_board_validation_requires_markdown_signature() -> None:
    registry_module = load_source_registry()
    real_board = (FIXTURES / "workable-myteam-jobs-2026-08-11.md").read_text(
        encoding="utf-8"
    )
    signed_empty_board = """# Acme — All Open Positions

| Title | Department | Location | Type | Salary | Posted | Details |
|-------|------------|----------|------|--------|--------|---------|

---
Powered by [Workable](https://www.workable.com)
"""

    assert not registry_module._endpoint_payload_is_valid(
        "workable", "<html><body>Workable jobs</body></html>"
    )
    assert registry_module._endpoint_payload_is_valid("workable", signed_empty_board)
    assert registry_module._endpoint_payload_is_valid("workable", real_board)


def test_generic_workable_endpoint_html_is_validation_failed(tmp_path: Path) -> None:
    registry_module = load_source_registry()
    career_hub = tmp_path / "Career Hub.md"
    career_hub.write_text(
        "| **Acme — Engineer** | "
        "[apply](https://apply.workable.com/acme/?source=private) |\n",
        encoding="utf-8",
    )
    requested: list[str] = []

    def fetcher(url: str, _timeout_seconds: float) -> str:
        requested.append(url)
        assert url == "https://apply.workable.com/acme/jobs.md"
        return "<html><body>Generic Workable page</body></html>"

    candidates = registry_module.import_candidates(
        career_hub_path=career_hub,
        resolve_url=lambda _url, _timeout_seconds: (_ for _ in ()).throw(
            AssertionError("direct ATS link should not resolve")
        ),
        fetcher=fetcher,
        deadline_seconds=5,
    )

    assert requested == ["https://apply.workable.com/acme/jobs.md"]
    assert len(candidates) == 1
    assert candidates[0]["status"] == "validation-failed"
    assert candidates[0]["reason"] == "public endpoint returned an unexpected payload"


@pytest.mark.parametrize(
    ("input_url", "resolved_url"),
    [
        ("https://[invalid", "https://[invalid"),
        (
            "https://redirect.test/private-token",
            "https://example.test:not-a-port/private-token",
        ),
    ],
)
def test_malformed_corpus_or_resolver_url_isolated_from_healthy_sibling(
    tmp_path: Path, input_url: str, resolved_url: str
) -> None:
    registry_module = load_source_registry()
    shushu = tmp_path / "shushu.csv"
    shushu.write_text(
        "Company,Role\n"
        f'"=HYPERLINK(""{input_url}"",""Malformed"")",Backend\n'
        '"=HYPERLINK(""https://jobs.lever.co/healthy/role"",""Healthy"")",Frontend\n',
        encoding="utf-8",
    )
    fetched: list[str] = []

    def resolver(url: str, _timeout_seconds: float) -> str:
        return resolved_url if url == input_url else url

    def fetcher(url: str, _timeout_seconds: float) -> str:
        fetched.append(url)
        return "[]" if url == "https://api.lever.co/v0/postings/healthy?mode=json" else ""

    candidates = registry_module.import_candidates(
        shushu_csv_path=shushu,
        resolve_url=resolver,
        fetcher=fetcher,
        deadline_seconds=5,
    )

    assert [(candidate["company"], candidate["status"]) for candidate in candidates] == [
        ("Malformed", "resolve-failed"),
        ("Healthy", "verified"),
    ]
    assert fetched == ["https://api.lever.co/v0/postings/healthy?mode=json"]
    serialized = json.dumps(candidates)
    assert "private-token" not in serialized
    assert "not-a-port" not in serialized


def test_malformed_page_link_does_not_hide_valid_sibling_link() -> None:
    registry_module = load_source_registry()
    body = "".join(
        [
            '<a href="https://[invalid/careers">broken</a>',
            '<a href="https://jobs.lever.co/healthy/role">valid ATS</a>',
            '<a href="/careers">valid career</a>',
        ]
    )

    assert registry_module._page_supported_urls("https://company.test/", body) == [
        "https://jobs.lever.co/healthy/role"
    ]
    assert registry_module._page_career_urls("https://company.test/", body) == [
        "https://company.test/careers"
    ]


def test_candidate_import_dedupes_tenant_and_merges_unique_provenance(
    tmp_path: Path,
) -> None:
    registry_module = load_source_registry()
    career_hub = tmp_path / "Career Hub.md"
    career_hub.write_text(
        "| **Acme — Role One** | [apply](https://jobs.lever.co/acme/job-1) |\n"
        "| **Acme — Role Two** | [apply](https://jobs.lever.co/acme/job-2) |\n",
        encoding="utf-8",
    )
    shushu = tmp_path / "shushu.csv"
    shushu.write_text(
        "Company,Role\n"
        '"=HYPERLINK(""https://jobs.lever.co/acme/job-3"",""Acme"")",Backend\n'
        '"=HYPERLINK(""https://jobs.lever.co/acme/job-3"",""Acme"")",Frontend\n'
        '"=HYPERLINK(""https://jobs.lever.co/beta/job-1"",""Beta"")",Backend\n',
        encoding="utf-8",
    )
    endpoint_calls: list[str] = []

    def fetcher(url: str, _timeout_seconds: float) -> str:
        endpoint_calls.append(url)
        return "[]"

    candidates = registry_module.import_candidates(
        career_hub_path=career_hub,
        shushu_csv_path=shushu,
        resolve_url=lambda _url, _timeout_seconds: (_ for _ in ()).throw(
            AssertionError("direct ATS links should not resolve")
        ),
        fetcher=fetcher,
        deadline_seconds=5,
    )

    assert endpoint_calls == [
        "https://api.lever.co/v0/postings/acme?mode=json",
        "https://api.lever.co/v0/postings/beta?mode=json",
    ]
    assert [candidate["identifiers"] for candidate in candidates] == [
        {"account": "acme"},
        {"account": "beta"},
    ]
    assert [candidate["status"] for candidate in candidates] == [
        "verified",
        "verified",
    ]
    assert candidates[0]["provenance"] == [
        {"kind": "career-hub", "reference": "Career Hub.md:line-1"},
        {"kind": "career-hub", "reference": "Career Hub.md:line-2"},
        {"kind": "shushu-csv", "reference": "shushu.csv:row-2"},
        {"kind": "shushu-csv", "reference": "shushu.csv:row-3"},
    ]


def test_candidate_import_keeps_merged_provenance_tenant_local(tmp_path: Path) -> None:
    registry_module = load_source_registry()
    career_hub = tmp_path / "Career Hub.md"
    career_hub.write_text(
        "| **Landing — Open Roles** | [careers](https://company.test/careers) |\n"
        "| **Tenant A — Engineer** | [apply](https://jobs.lever.co/tenant-a/job) |\n",
        encoding="utf-8",
    )
    endpoint_calls: list[str] = []

    def fetcher(url: str, _timeout_seconds: float) -> str:
        if url == "https://company.test/careers":
            return (
                '<a href="https://jobs.lever.co/tenant-a/job">A</a>'
                '<a href="https://jobs.lever.co/tenant-b/job">B</a>'
            )
        endpoint_calls.append(url)
        return "[]"

    candidates = registry_module.import_candidates(
        career_hub_path=career_hub,
        resolve_url=lambda url, _timeout_seconds: url,
        fetcher=fetcher,
        deadline_seconds=5,
    )

    assert endpoint_calls == [
        "https://api.lever.co/v0/postings/tenant-a?mode=json",
        "https://api.lever.co/v0/postings/tenant-b?mode=json",
    ]
    assert [candidate["identifiers"] for candidate in candidates] == [
        {"account": "tenant-a"},
        {"account": "tenant-b"},
    ]
    assert candidates[0]["provenance"] == [
        {"kind": "career-hub", "reference": "Career Hub.md:line-1"},
        {"kind": "career-hub", "reference": "Career Hub.md:line-2"},
    ]
    assert candidates[1]["provenance"] == [
        {"kind": "career-hub", "reference": "Career Hub.md:line-1"}
    ]
    assert candidates[0]["provenance"] is not candidates[1]["provenance"]


def test_registry_rejects_careers_url_that_names_a_different_tenant(
    tmp_path: Path,
) -> None:
    registry_module = load_source_registry()
    registry_path = tmp_path / "registry.json"
    registry_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "tenants": [
                    {
                        "source": "greenhouse",
                        "identifiers": {"board": "expected-board"},
                        "company": "Mismatch",
                        "careers_url": "https://job-boards.greenhouse.io/other-board",
                        "provenance": [
                            {"kind": "test-fixture", "reference": "fixture"}
                        ],
                        "last_verified_at": "2026-08-20",
                        "enabled": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    report = registry_module.load_registry(
        registry_path, as_of=date(2026, 8, 26), max_age_days=30
    )

    assert report.valid == []
    assert len(report.invalid) == 1
    assert "tenant identifiers" in report.invalid[0]["reason"]


def test_malformed_careers_url_isolated_from_healthy_sibling(tmp_path: Path) -> None:
    registry_module = load_source_registry()

    def entry(board: str, company: str, careers_url: str) -> dict[str, object]:
        return {
            "source": "greenhouse",
            "identifiers": {"board": board},
            "company": company,
            "careers_url": careers_url,
            "provenance": [{"kind": "test-fixture", "reference": company}],
            "last_verified_at": "2026-08-20",
            "enabled": True,
        }

    registry_path = tmp_path / "registry.json"
    registry_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "tenants": [
                    entry("bad", "Bad URL", "https://[invalid"),
                    entry(
                        "healthy",
                        "Healthy",
                        "https://job-boards.greenhouse.io/healthy",
                    ),
                ],
            }
        ),
        encoding="utf-8",
    )

    report = registry_module.load_registry(
        registry_path, as_of=date(2026, 8, 26), max_age_days=30
    )

    assert [tenant["company"] for tenant in report.valid] == ["Healthy"]
    assert [(issue["company"], issue["status"]) for issue in report.invalid] == [
        ("Bad URL", "invalid")
    ]
    assert "careers_url" in report.invalid[0]["reason"]


def test_unhashable_source_isolated_from_healthy_sibling(tmp_path: Path) -> None:
    registry_module = load_source_registry()
    registry_path = tmp_path / "registry.json"
    registry_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "tenants": [
                    {
                        "source": [],
                        "identifiers": {"board": "bad"},
                        "company": "Bad Source",
                        "careers_url": "https://job-boards.greenhouse.io/bad",
                        "provenance": [
                            {"kind": "test-fixture", "reference": "bad-source"}
                        ],
                        "last_verified_at": "2026-08-20",
                        "enabled": True,
                    },
                    {
                        "source": "greenhouse",
                        "identifiers": {"board": "healthy"},
                        "company": "Healthy",
                        "careers_url": "https://job-boards.greenhouse.io/healthy",
                        "provenance": [
                            {"kind": "test-fixture", "reference": "healthy"}
                        ],
                        "last_verified_at": "2026-08-20",
                        "enabled": True,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    report = registry_module.load_registry(
        registry_path, as_of=date(2026, 8, 26), max_age_days=30
    )

    assert [tenant["company"] for tenant in report.valid] == ["Healthy"]
    assert [(issue["company"], issue["status"]) for issue in report.invalid] == [
        ("Bad Source", "invalid")
    ]
    assert "unsupported source" in report.invalid[0]["reason"]


def test_registry_rejects_duplicate_tenant_without_hiding_first_entry(
    tmp_path: Path,
) -> None:
    registry_module = load_source_registry()

    def entry(company: str) -> dict[str, object]:
        return {
            "source": "greenhouse",
            "identifiers": {"board": "same-board"},
            "company": company,
            "careers_url": "https://job-boards.greenhouse.io/same-board",
            "provenance": [{"kind": "test-fixture", "reference": company}],
            "last_verified_at": "2026-08-20",
            "enabled": True,
        }

    registry_path = tmp_path / "registry.json"
    registry_path.write_text(
        json.dumps(
            {"schema_version": 1, "tenants": [entry("First"), entry("Duplicate")]}
        ),
        encoding="utf-8",
    )

    report = registry_module.load_registry(
        registry_path, as_of=date(2026, 8, 26), max_age_days=30
    )

    assert [tenant["company"] for tenant in report.valid] == ["First"]
    assert [(issue["company"], issue["status"]) for issue in report.invalid] == [
        ("Duplicate", "invalid")
    ]
    assert "duplicate tenant" in report.invalid[0]["reason"]


def test_registry_dry_run_lists_each_status_without_secret_values(tmp_path: Path) -> None:
    def entry(source: str, tenant: str, company: str, verified: str) -> dict[str, object]:
        identifier_name = "board" if source == "greenhouse" else "account"
        host = "job-boards.greenhouse.io" if source == "greenhouse" else "jobs.lever.co"
        return {
            "source": source,
            "identifiers": {identifier_name: tenant},
            "company": company,
            "careers_url": f"https://{host}/{tenant}",
            "provenance": [{"kind": "test-fixture", "reference": "fixture"}],
            "last_verified_at": verified,
            "enabled": True,
        }

    invalid = entry("greenhouse", "broken", "Broken", "2026-08-20")
    invalid["api_key"] = "TOP-SECRET-VALUE"
    registry_path = tmp_path / "registry.json"
    registry_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "tenants": [
                    entry("greenhouse", "fresh", "Fresh", "2026-08-20"),
                    invalid,
                    entry("lever", "old", "Old", "2026-01-01"),
                ],
            }
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            "python3",
            str(REGISTRY_MODULE_PATH),
            "--dry-run",
            "--registry",
            str(registry_path),
            "--as-of",
            "2026-08-26",
            "--max-age-days",
            "30",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1, result.stderr
    assert "VALID (1)" in result.stdout
    assert "INVALID (1)" in result.stdout
    assert "STALE (1)" in result.stdout
    assert "Fresh" in result.stdout
    assert "Broken" in result.stdout
    assert "Old" in result.stdout
    assert "TOP-SECRET-VALUE" not in result.stdout


def test_registry_dry_run_treats_disabled_only_as_healthy(tmp_path: Path) -> None:
    registry_path = tmp_path / "registry.json"
    registry_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "tenants": [
                    {
                        "source": "lever",
                        "identifiers": {"account": "paused"},
                        "company": "Paused",
                        "careers_url": "https://jobs.lever.co/paused",
                        "provenance": [
                            {"kind": "test-fixture", "reference": "paused"}
                        ],
                        "last_verified_at": "2026-08-20",
                        "enabled": False,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            "python3",
            str(REGISTRY_MODULE_PATH),
            "--dry-run",
            "--registry",
            str(registry_path),
            "--as-of",
            "2026-08-26",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "VALID (0)" in result.stdout
    assert "INVALID (0)" in result.stdout
    assert "STALE (0)" in result.stdout
    assert "DISABLED (1)" in result.stdout


def test_candidate_import_budget_preserves_unchecked_rows_for_review(
    tmp_path: Path,
) -> None:
    registry_module = load_source_registry()
    assert "deadline_seconds" in inspect.signature(
        registry_module.import_candidates
    ).parameters
    shushu = tmp_path / "shushu.csv"
    shushu.write_text(
        "Company,Role\n"
        '"=HYPERLINK(""https://redirect.test/one"",""One"")",Backend\n'
        '"=HYPERLINK(""https://redirect.test/two"",""Two"")",Frontend\n',
        encoding="utf-8",
    )
    calls: list[str] = []

    candidates = registry_module.import_candidates(
        shushu_csv_path=shushu,
        resolve_url=lambda url: calls.append(url) or url,
        fetcher=lambda _url: None,
        deadline_seconds=0,
    )

    assert calls == []
    assert [candidate["company"] for candidate in candidates] == ["One", "Two"]
    assert {candidate["status"] for candidate in candidates} == {"budget-exhausted"}


def test_positive_import_budget_stops_between_network_stages(
    tmp_path: Path,
) -> None:
    registry_module = load_source_registry()
    shushu = tmp_path / "shushu.csv"
    shushu.write_text(
        "Company,Role\n"
        '"=HYPERLINK(""https://redirect.test/one"",""One"")",Backend\n'
        '"=HYPERLINK(""https://redirect.test/two"",""Two"")",Frontend\n',
        encoding="utf-8",
    )
    calls: list[str] = []
    supplied_timeouts: list[tuple[float, ...]] = []

    def resolver(_url: str, *timeouts: float) -> str:
        calls.append("resolve")
        supplied_timeouts.append(timeouts)
        time.sleep(0.25)
        return "https://one.example/"

    def fetcher(_url: str, *timeouts: float) -> str:
        calls.append("fetch")
        supplied_timeouts.append(timeouts)
        return "<p>No ATS link.</p>"

    candidates = registry_module.import_candidates(
        shushu_csv_path=shushu,
        resolve_url=resolver,
        fetcher=fetcher,
        deadline_seconds=0.1,
    )

    assert calls == ["resolve"]
    assert len(supplied_timeouts[0]) == 1
    assert 0 < supplied_timeouts[0][0] <= 0.1
    assert [candidate["status"] for candidate in candidates] == [
        "budget-exhausted",
        "budget-exhausted",
    ]


def test_import_budget_expiry_during_raised_callback_preserves_remaining_rows(
    tmp_path: Path,
) -> None:
    registry_module = load_source_registry()
    shushu = tmp_path / "shushu.csv"
    shushu.write_text(
        "Company,Role\n"
        '"=HYPERLINK(""https://redirect.test/one"",""One"")",Backend\n'
        '"=HYPERLINK(""https://redirect.test/two"",""Two"")",Frontend\n',
        encoding="utf-8",
    )
    calls: list[str] = []

    def slow_failing_resolver(_url: str, _timeout_seconds: float) -> str:
        calls.append("resolve")
        time.sleep(0.25)
        raise TimeoutError("resolver exceeded its supplied timeout")

    candidates = registry_module.import_candidates(
        shushu_csv_path=shushu,
        resolve_url=slow_failing_resolver,
        fetcher=lambda _url, _timeout_seconds: "",
        deadline_seconds=0.1,
    )

    assert calls == ["resolve"]
    assert [candidate["status"] for candidate in candidates] == [
        "budget-exhausted",
        "budget-exhausted",
    ]


def test_fast_resolver_exception_retains_truthful_failure_status(tmp_path: Path) -> None:
    registry_module = load_source_registry()
    shushu = tmp_path / "shushu.csv"
    shushu.write_text(
        "Company,Role\n"
        '"=HYPERLINK(""https://redirect.test/acme"",""Acme"")",Backend\n',
        encoding="utf-8",
    )

    def failing_resolver(_url: str, _timeout_seconds: float) -> str:
        raise TimeoutError("fast resolver failure")

    candidates = registry_module.import_candidates(
        shushu_csv_path=shushu,
        resolve_url=failing_resolver,
        fetcher=lambda _url, _timeout_seconds: "",
        deadline_seconds=1,
    )

    assert len(candidates) == 1
    assert candidates[0]["status"] == "resolve-failed"
    assert candidates[0]["reason"] == "redirect resolution failed: TimeoutError"


def test_default_network_helpers_never_expand_remaining_timeout(monkeypatch) -> None:
    registry_module = load_source_registry()
    observed_timeouts: list[float] = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def geturl(self) -> str:
            return "https://example.test/final"

        def read(self) -> bytes:
            return b"{}"

    def fake_open(_url: str, timeout: float):
        observed_timeouts.append(timeout)
        return Response()

    monkeypatch.setattr(registry_module, "_open_public_https", fake_open)

    registry_module._default_resolve_url("https://example.test", 0.0001)
    registry_module._default_fetcher("https://example.test", 0.0001)
    registry_module._default_resolve_url("https://example.test", 30.0)
    registry_module._default_fetcher("https://example.test", 30.0)

    assert observed_timeouts == [0.0001, 0.0001, 15.0, 20.0]


@pytest.mark.parametrize(
    ("failure_stage", "expected_status", "expected_reason"),
    [
        (
            "career-resolve",
            "resolve-failed",
            "career redirect resolution failed: TimeoutError",
        ),
        (
            "career-fetch",
            "validation-failed",
            "career page request failed: TimeoutError",
        ),
    ],
)
def test_nested_career_failure_is_not_reported_as_unsupported(
    tmp_path: Path,
    failure_stage: str,
    expected_status: str,
    expected_reason: str,
) -> None:
    registry_module = load_source_registry()
    shushu = tmp_path / "shushu.csv"
    shushu.write_text(
        "Company,Role\n"
        '"=HYPERLINK(""https://redirect.test/acme"",""Acme"")",Backend\n',
        encoding="utf-8",
    )

    def resolver(url: str, _timeout_seconds: float) -> str:
        if url == "https://redirect.test/acme":
            return "https://acme.example/"
        if failure_stage == "career-resolve":
            raise TimeoutError("career redirect timed out")
        return url

    def fetcher(url: str, _timeout_seconds: float) -> str:
        if url == "https://acme.example/":
            return '<a href="/careers">Careers</a>'
        if failure_stage == "career-fetch":
            raise TimeoutError("career page timed out")
        return ""

    candidates = registry_module.import_candidates(
        shushu_csv_path=shushu,
        resolve_url=resolver,
        fetcher=fetcher,
        deadline_seconds=1,
    )

    assert len(candidates) == 1
    assert candidates[0]["company"] == "Acme"
    assert candidates[0]["status"] == expected_status
    assert candidates[0]["reason"] == expected_reason


def test_cross_source_dedupe_uses_normalized_company_and_title_after_id() -> None:
    harvest = load_harvest()
    postings = [
        {
            "id": "4450000000",
            "company": "Acme, Inc.",
            "title": "Full-Stack Engineer",
        },
        {
            "id": "greenhouse:acme:1234",
            "company": "  ACME INC  ",
            "title": "Full Stack   Engineer",
        },
        {
            "id": "lever:other:uuid",
            "company": "Other",
            "title": "Full Stack Engineer",
        },
    ]

    assert harvest.dedupe_postings(postings, set()) == [postings[0], postings[2]]


def test_disabled_sources_preserve_distinct_linkedin_ids_with_same_title() -> None:
    harvest = load_harvest()
    postings = [
        {"id": "1", "company": "Acme", "title": "Software Engineer"},
        {"id": "2", "company": "Acme", "title": "Software Engineer"},
    ]

    assert harvest.dedupe_postings(postings, set()) == postings


def test_noon_cross_source_dedupe_reads_only_the_current_day(tmp_path: Path) -> None:
    harvest = load_harvest()
    current = tmp_path / "2026-08-12.jsonl"
    current.write_text(
        json.dumps(
            {
                "id": "4450000000",
                "company": "Acme, Inc.",
                "title": "Full-Stack Engineer",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    candidate = {
        "id": "greenhouse:acme:1234",
        "company": "ACME INC",
        "title": "Full Stack Engineer",
    }

    seen = harvest.load_seen_secondary_keys(current)

    assert harvest.dedupe_postings([candidate], set(), seen) == []


def test_source_failure_warns_and_does_not_drop_other_sources(monkeypatch, caplog) -> None:
    harvest = load_harvest()

    class Broken:
        @staticmethod
        def fetch(*_args, **_kwargs):
            raise RuntimeError("blocked")

    class Healthy:
        @staticmethod
        def fetch(*_args, **_kwargs):
            return [
                {
                    "id": "lever:ok:1",
                    "source": "lever",
                    "jd_fetched": True,
                    "jd_text": "description",
                }
            ]

    modules = {"comeet": Broken, "lever": Healthy}
    monkeypatch.setattr(harvest, "load_source_adapter", modules.__getitem__)

    postings, warnings = harvest.harvest_sources(
        {"comeet": [{}], "lever": [{}]},
        {"comeet", "lever"},
        fetcher=lambda _url: None,
        before_request=lambda: None,
    )

    assert postings == [
        {
            "id": "lever:ok:1",
            "source": "lever",
            "jd_fetched": True,
            "jd_text": "description",
        }
    ]
    assert warnings == 1
    assert "Keeping feed after comeet seed failure" in caplog.text


def test_source_failure_isolated_to_one_seed_not_its_siblings(monkeypatch, caplog) -> None:
    harvest = load_harvest()

    class Greenhouse:
        @staticmethod
        def fetch(query, **_kwargs):
            if query["board"] == "bad":
                raise RuntimeError("404")
            return [
                {
                    "id": f"greenhouse:{query['board']}:1",
                    "source": "greenhouse",
                    "jd_fetched": True,
                    "jd_text": "description",
                }
            ]

    monkeypatch.setattr(harvest, "load_source_adapter", lambda _name: Greenhouse)

    postings, warnings = harvest.harvest_sources(
        {"greenhouse": [{"board": "good1"}, {"board": "bad"}, {"board": "good2"}]},
        {"greenhouse"},
        fetcher=lambda _url: None,
        before_request=lambda: None,
    )

    assert [posting["id"] for posting in postings] == [
        "greenhouse:good1:1",
        "greenhouse:good2:1",
    ]
    assert warnings == 1
    assert "greenhouse seed failure" in caplog.text


@pytest.mark.parametrize(
    "bad_sources",
    [
        {"comeet": "not-a-list"},
        {"smartrecruiters": [{"board": "future-seed"}]},
    ],
)
def test_enabled_source_config_error_never_kills_linkedin_feed(
    tmp_path: Path, monkeypatch, caplog, bad_sources
) -> None:
    harvest = load_harvest()
    config = json.loads(SEARCHES_PATH.read_text(encoding="utf-8"))
    config["sources"] = bad_sources
    config_path = tmp_path / "searches.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    linkedin = {
        "id": "4450000000",
        "title": "Software Engineer",
        "company": "Acme",
        "location": "Israel",
        "url": "https://linkedin.example/4450000000",
        "posted_ago": "1 hour ago",
        "jd_fetched": True,
        "jd_text": "React TypeScript",
    }
    monkeypatch.setattr(
        harvest, "harvest_search", lambda *_args, **_kwargs: ([dict(linkedin)], 0)
    )

    result = harvest.run_pipeline(
        config_path=config_path,
        profile_path=HERE.parent / "profile.example.yaml",
        output_dir=tmp_path / "output",
        date_string="2026-08-11",
        harvested_at="2026-08-11T18:00:00Z",
        max_pages=1,
        fetcher=lambda _url: None,
        before_request=lambda: None,
        enabled_sources={"comeet"},
    )

    assert result["new_count"] == 1
    assert result["warning_count"] >= 1
    assert "Keeping LinkedIn feed after source config" in caplog.text



def test_pipeline_source_counts_are_unique_postings_not_query_card_hits(
    tmp_path: Path, monkeypatch
) -> None:
    harvest = load_harvest()
    linkedin = {
        "id": "4450000000",
        "title": "Full Stack Engineer",
        "company": "Acme",
        "location": "Israel",
        "url": "https://linkedin.example/4450000000",
        "posted_ago": "1 hour ago",
        "source": "linkedin",
        "jd_fetched": True,
        "jd_text": "React TypeScript",
    }
    lever = {
        "id": "lever:other:uuid",
        "title": "Backend Engineer",
        "company": "Other",
        "location": "Israel",
        "url": "https://lever.example/uuid",
        "posted_at": "2026-08-11T17:00:00Z",
        "posted_ago": "2026-08-11 17:00 UTC",
        "source": "lever",
        "jd_fetched": True,
        "jd_text": "Node.js TypeScript",
    }
    monkeypatch.setattr(
        harvest,
        "harvest_search",
        lambda *_args, **_kwargs: ([dict(linkedin), dict(linkedin)], 0),
    )
    monkeypatch.setattr(
        harvest,
        "harvest_sources",
        lambda *_args, **_kwargs: ([dict(lever)], 0),
    )

    result = harvest.run_pipeline(
        config_path=SEARCHES_PATH,
        profile_path=HERE.parent / "profile.example.yaml",
        output_dir=tmp_path,
        date_string="2026-08-11",
        harvested_at="2026-08-11T18:00:00Z",
        max_pages=1,
        fetcher=lambda _url: None,
        before_request=lambda: None,
        enabled_sources={"lever"},
    )

    assert result["harvested_count"] == 21
    assert result["source_counts"] == {"linkedin": 1, "lever": 1}


def test_pipeline_source_counts_match_new_rows_on_noon_rerun(
    tmp_path: Path, monkeypatch
) -> None:
    harvest = load_harvest()
    linkedin = {
        "id": "4450000000", "title": "Full Stack Engineer", "company": "Acme",
        "location": "Israel", "url": "https://linkedin.example/4450000000",
        "posted_ago": "1 hour ago", "source": "linkedin", "jd_fetched": True,
        "jd_text": "React TypeScript",
    }
    lever = {
        "id": "lever:other:uuid", "title": "Backend Engineer", "company": "Other",
        "location": "Israel", "url": "https://lever.example/uuid",
        "posted_ago": "1 hour ago", "source": "lever", "jd_fetched": True,
        "jd_text": "Node.js TypeScript",
    }
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    (output_dir / "2026-08-11.jsonl").write_text(
        "\n".join(json.dumps(row) for row in (linkedin, lever)) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        harvest, "harvest_search", lambda *_args, **_kwargs: ([dict(linkedin)], 0)
    )
    monkeypatch.setattr(
        harvest, "harvest_sources", lambda *_args, **_kwargs: ([dict(lever)], 0)
    )

    result = harvest.run_pipeline(
        config_path=SEARCHES_PATH,
        profile_path=HERE.parent / "profile.example.yaml",
        output_dir=output_dir,
        date_string="2026-08-11",
        harvested_at="2026-08-11T18:00:00Z",
        max_pages=1,
        fetcher=lambda _url: None,
        before_request=lambda: None,
        enabled_sources={"lever"},
    )

    assert result["new_count"] == 0
    assert result["source_counts"] == {"linkedin": 0, "lever": 0}


def test_pipeline_does_not_reemit_prior_day_native_ats_posting(
    tmp_path: Path, monkeypatch
) -> None:
    harvest = load_harvest()
    lever = {
        "id": "lever:acme:stable-id",
        "title": "Backend Engineer",
        "company": "Acme",
        "location": "Israel",
        "url": "https://lever.example/stable-id",
        "posted_at": "2026-01-01T00:00:00Z",
        "posted_ago": "2026-01-01 00:00 UTC",
        "source": "lever",
        "jd_fetched": True,
        "jd_text": "Node.js TypeScript",
    }
    (tmp_path / "2026-08-11.jsonl").write_text(
        json.dumps(lever) + "\n", encoding="utf-8"
    )
    monkeypatch.setattr(
        harvest, "harvest_search", lambda *_args, **_kwargs: ([], 0)
    )
    monkeypatch.setattr(
        harvest, "harvest_sources", lambda *_args, **_kwargs: ([dict(lever)], 0)
    )

    result = harvest.run_pipeline(
        config_path=SEARCHES_PATH,
        profile_path=HERE.parent / "profile.example.yaml",
        output_dir=tmp_path,
        date_string="2026-08-12",
        harvested_at="2026-08-12T09:00:00Z",
        max_pages=1,
        fetcher=lambda _url: None,
        before_request=lambda: None,
        enabled_sources={"lever"},
    )

    assert result["new_count"] == 0
    assert result["skipped_seen"] == 1
    assert result["source_counts"] == {"linkedin": 0, "lever": 0}
    assert (tmp_path / "2026-08-12.jsonl").read_text(encoding="utf-8") == ""


def test_ats_postings_are_filtered_by_title_synonyms_and_israel_location() -> None:
    harvest = load_harvest()
    searches = harvest.load_searches(SEARCHES_PATH)
    postings = [
        {"id": "1", "title": "Software Engineer", "location": "Tel Aviv"},
        {"id": "2", "title": "Software Engineer", "location": "Bangalore"},
        {"id": "3", "title": "Account Executive", "location": "Tel Aviv, Israel"},
        {"id": "4", "title": "Senior Backend Engineer", "location": "Israel (Remote)"},
        {"id": "5", "title": "Full-Stack Engineer", "location": "Israel, Tel Aviv"},
    ]

    assert [
        posting["id"]
        for posting in harvest.filter_source_postings(postings, searches)
    ] == ["1", "4", "5"]


def test_ats_title_matching_covers_common_engineer_developer_variants(caplog) -> None:
    harvest = load_harvest()
    searches = harvest.load_searches(SEARCHES_PATH)
    titles = [
        "Fullstack Engineer", "Frontend Developer", "Front End Engineer",
        "Web Developer", "Software Developer", "Full Stack Web Developer",
        "Machine Learning Engineer",
    ]
    postings = [
        {
            "id": str(index), "title": title, "location": "Tel Aviv, Israel",
            "source": "greenhouse", "posted_at": "2026-08-11T17:00:00Z",
        }
        for index, title in enumerate(titles)
    ]

    matched = harvest.filter_source_postings(postings, searches)

    assert [posting["title"] for posting in matched] == titles


def test_shipped_searches_match_a_representative_ats_posting() -> None:
    harvest = load_harvest()
    searches = harvest.load_searches(SEARCHES_PATH)
    representative = {
        "id": "lever:example:backend-1",
        "title": "Backend Engineer",
        "location": "Tel Aviv, Israel",
        "source": "lever",
        "posted_at": "2026-08-11T17:00:00Z",
    }

    assert harvest.filter_source_postings([representative], searches) == [
        representative
    ]


def test_ats_first_seen_semantics_admit_old_native_postings(caplog) -> None:
    harvest = load_harvest()
    caplog.set_level("INFO", logger="coach.jobfeed")
    searches = [{"keywords": "Software Engineer", "location": "Israel", "recency": "r10800"}]
    postings = [
        {
            "id": "recent", "title": "Software Engineer", "location": "Israel",
            "source": "greenhouse", "posted_at": "2026-08-11T17:00:00Z",
        },
        {
            "id": "old", "title": "Software Engineer", "location": "Israel",
            "source": "greenhouse", "posted_at": "2026-08-11T12:00:00Z",
        },
    ]

    matched = harvest.filter_source_postings(postings, searches)

    assert [posting["id"] for posting in matched] == ["recent", "old"]
    assert "Filtered" not in caplog.text


def test_workable_first_seen_semantics_ignore_board_posted_date() -> None:
    harvest = load_harvest()
    searches = [
        {"keywords": "Software Engineer", "location": "Israel", "recency": "r10800"}
    ]
    postings = [
        {
            "id": "workable:acme:today",
            "title": "Software Engineer",
            "location": "Tel Aviv, Israel",
            "source": "workable",
            "posted_at": "2026-08-12T00:00:00Z",
        },
        {
            "id": "workable:acme:yesterday",
            "title": "Software Engineer",
            "location": "Tel Aviv, Israel",
            "source": "workable",
            "posted_at": "2026-08-11T00:00:00Z",
        },
    ]

    matched = harvest.filter_source_postings(postings, searches)

    assert [posting["id"] for posting in matched] == [
        "workable:acme:today",
        "workable:acme:yesterday",
    ]


def test_pipeline_uses_batch_employer_classification_on_scored_rows(
    tmp_path: Path, monkeypatch
) -> None:
    harvest = load_harvest()
    linkedin = {
        "id": "4450000000",
        "title": "Full Stack Engineer",
        "company": "Acme",
        "location": "Israel",
        "url": "https://linkedin.example/4450000000",
        "posted_ago": "1 hour ago",
        "source": "linkedin",
        "jd_fetched": True,
        "jd_text": "React TypeScript",
    }
    calls: list[list[str]] = []

    monkeypatch.setattr(
        harvest, "harvest_search", lambda *_args, **_kwargs: ([dict(linkedin)], 0)
    )

    def classify_batch(postings):
        calls.append([str(posting["id"]) for posting in postings])
        return [
            {
                **posting,
                "employer_class": "staffing",
                "employer_class_note": "classified through production batch",
            }
            for posting in postings
        ]

    monkeypatch.setattr(harvest, "apply_employer_classification", classify_batch)

    harvest.run_pipeline(
        config_path=SEARCHES_PATH,
        profile_path=HERE.parent / "profile.example.yaml",
        output_dir=tmp_path,
        date_string="2026-08-12",
        harvested_at="2026-08-12T09:00:00Z",
        max_pages=1,
        fetcher=lambda _url: None,
        before_request=lambda: None,
    )

    rows = [
        json.loads(line)
        for line in (tmp_path / "2026-08-12.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert calls == [["4450000000"]]
    assert rows[0]["employer_class"] == "staffing"
    assert rows[0]["employer_class_note"] == "classified through production batch"


def test_missing_ats_jd_warning_is_counted_only_after_filtering() -> None:
    harvest = load_harvest()
    searches = [{"keywords": "Software Engineer", "location": "Israel", "recency": "r10800"}]
    postings = [
        {
            "id": "relevant", "title": "Software Engineer", "location": "Israel",
            "source": "greenhouse", "posted_at": "2026-08-11T17:00:00Z",
            "jd_fetched": True,
        },
        {
            "id": "irrelevant", "title": "Account Executive", "location": "Israel",
            "source": "greenhouse", "posted_at": "2026-08-11T17:00:00Z",
            "jd_fetched": False,
        },
    ]

    matched = harvest.filter_source_postings(postings, searches)

    assert harvest.count_missing_source_jds(matched) == 0


def test_workable_filters_board_rows_before_fetching_job_details(caplog) -> None:
    module = load_source("workable")
    caplog.set_level("INFO", logger="coach.jobfeed.source.workable")
    board = (FIXTURES / "workable-myteam-jobs-2026-08-11.md").read_text(
        encoding="utf-8"
    )
    detail = (
        FIXTURES / "workable-myteam-job-99FDF530F1-2026-08-11.md"
    ).read_text(encoding="utf-8")
    requested: list[str] = []

    def fetcher(url: str) -> str:
        requested.append(url)
        return detail if "/jobs/view/" in url else board

    postings = module.fetch(
        {"account": "myteam", "company": "my team"},
        fetcher=fetcher,
        before_request=lambda: None,
        posting_filter=lambda posting: posting["id"] == "workable:myteam:99FDF530F1",
    )

    assert [posting["id"] for posting in postings] == ["workable:myteam:99FDF530F1"]
    assert requested == [
        "https://apply.workable.com/myteam/jobs.md",
        "https://apply.workable.com/myteam/jobs/view/99FDF530F1.md",
    ]
    assert "Filtered 17 of 18 workable postings before detail fetch" in caplog.text



def test_disabled_sources_do_not_parse_or_validate_source_config(
    tmp_path: Path, monkeypatch
) -> None:
    harvest = load_harvest()
    config = json.loads(SEARCHES_PATH.read_text(encoding="utf-8"))
    config["sources"] = "deliberately-invalid-but-disabled"
    config_path = tmp_path / "searches.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    monkeypatch.setattr(
        harvest, "harvest_search", lambda *_args, **_kwargs: ([], 0)
    )

    result = harvest.run_pipeline(
        config_path=config_path,
        profile_path=HERE.parent / "profile.example.yaml",
        output_dir=tmp_path / "output",
        date_string="2026-08-11",
        harvested_at="2026-08-11T18:00:00Z",
        max_pages=1,
        fetcher=lambda _url: None,
        before_request=lambda: None,
    )

    assert result["harvested_count"] == 0
    assert "source_counts" not in result


def test_native_ats_jd_skips_linkedin_job_endpoint() -> None:
    harvest = load_harvest()
    posting = {
        "id": "greenhouse:guidde:123",
        "source": "greenhouse",
        "jd_fetched": True,
        "jd_text": "React and TypeScript role",
    }

    enriched, warnings = harvest.fetch_job_descriptions(
        [posting],
        fetcher=lambda _url: (_ for _ in ()).throw(AssertionError("network called")),
        sleep=lambda _seconds: (_ for _ in ()).throw(AssertionError("pacer called")),
    )

    assert enriched == [posting]
    assert warnings == 0


def test_missing_native_ats_jd_still_skips_linkedin_job_endpoint() -> None:
    harvest = load_harvest()
    posting = {
        "id": "greenhouse:guidde:123",
        "source": "greenhouse",
        "jd_fetched": False,
        "jd_text": "",
    }

    enriched, warnings = harvest.fetch_job_descriptions(
        [posting],
        fetcher=lambda _url: (_ for _ in ()).throw(AssertionError("network called")),
        sleep=lambda _seconds: (_ for _ in ()).throw(AssertionError("pacer called")),
    )

    assert enriched == [posting]
    assert warnings == 0


def test_current_python_can_import_every_source_module() -> None:
    paths = [str(HERE / "sources" / f"{name}.py") for name in SOURCE_NAMES]
    paths.append(str(REGISTRY_MODULE_PATH))
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import runpy,sys; [runpy.run_path(path) for path in sys.argv[1:]]",
            *paths,
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
