#!/usr/bin/env python3
"""Tests for fail-closed LinkedIn guest-page JD fetching."""

from __future__ import annotations

import gzip
import importlib.util
from pathlib import Path
from urllib.error import URLError


HERE = Path(__file__).resolve().parent
MODULE_PATH = HERE / "jd_fetch.py"
FIXTURE_PATH = HERE / "fixtures" / "linkedin-guest-jd-abra-2026-08-09.html"


def load_jd_fetch_module():
    spec = importlib.util.spec_from_file_location("job_feed_jd_fetch", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeHeaders(dict):
    # Instance method intentionally matches the urllib headers protocol.
    def get_content_charset(self):  # skipcq: PYL-R0201
        return "utf-8"


class FakeResponse:
    def __init__(self, body: bytes, headers: dict[str, str] | None = None) -> None:
        self.body = body
        self.headers = FakeHeaders(headers or {})

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def read(self) -> bytes:
        return self.body


def test_extracts_real_saved_guest_markup_without_show_controls() -> None:
    jd_fetch = load_jd_fetch_module()

    description = jd_fetch.extract_full_jd(FIXTURE_PATH.read_text(encoding="utf-8"))

    assert description.startswith(
        "abra professional services is seeking a talented Full Stack Developer"
    )
    assert "Proven experience with C# .NET – Mandatory" in description
    assert "Experience with AngularJS – Advantage" in description
    assert "Show more" not in description
    assert "Show less" not in description
    assert "  " not in description


def test_falls_back_to_description_text_container_and_normalizes_whitespace() -> None:
    jd_fetch = load_jd_fetch_module()
    html = """
    <main>
      <div class="description__text description__text--rich">
        First line&nbsp;with spacing.<br>
        <p>Second <strong>nested</strong> line.</p>
        <button>Show more</button><button>Show less</button>
      </div>
    </main>
    """

    assert jd_fetch.extract_full_jd(html) == (
        "First line with spacing. Second nested line."
    )


def test_empty_or_blocked_markup_returns_no_description() -> None:
    jd_fetch = load_jd_fetch_module()

    assert jd_fetch.extract_full_jd("<html><title>Join LinkedIn</title></html>") == ""
    assert jd_fetch.extract_full_jd("") == ""


def test_unbalanced_list_markup_stays_inside_description_container() -> None:
    jd_fetch = load_jd_fetch_module()
    html = """
    <div class="show-more-less-html__markup">
      <p>Real JD start.
      <ul><li>Item one<li>Item two</ul>
    </div></div>
    <footer>FOOTER GARBAGE SHOULD NOT APPEAR</footer>
    <script>var trackingPayload = {"a": 1};</script>
    """

    description = jd_fetch.extract_full_jd(html)

    assert description == "Real JD start. Item one Item two"
    assert "FOOTER GARBAGE" not in description
    assert "trackingPayload" not in description


def test_ignores_non_description_subtrees_without_deleting_legitimate_prose() -> None:
    jd_fetch = load_jd_fetch_module()
    html = """
    <div class="description__text">
      You will show more initiative than most.
      <style>.tracking { color: red; }</style>
      <script>window.trackingPayload = {"a": 1};</script>
      <button>Show more</button>
      <svg><text>decorative label</text></svg>
      Build reliable products for customers.
    </div>
    """

    assert jd_fetch.extract_full_jd(html) == (
        "You will show more initiative than most. "
        "Build reliable products for customers."
    )


def test_fetch_full_jd_uses_browser_headers_timeout_and_decodes_gzip() -> None:
    jd_fetch = load_jd_fetch_module()
    fixture = FIXTURE_PATH.read_bytes()
    observed: dict[str, object] = {}

    def opener(request, timeout):
        observed["url"] = request.full_url
        observed["user_agent"] = request.get_header("User-agent")
        observed["accept_encoding"] = request.get_header("Accept-encoding")
        observed["timeout"] = timeout
        return FakeResponse(gzip.compress(fixture), {"Content-Encoding": "gzip"})

    result = jd_fetch.fetch_full_jd(
        "https://www.linkedin.com/jobs/view/example-123",
        opener=opener,
        timeout=17,
    )

    assert result["fetch_method"] == "guest-html"
    assert result["fetch_error"] is None
    assert result["jd_chars"] == len(result["jd_text"])
    assert result["jd_chars"] > 200
    assert observed == {
        "url": "https://www.linkedin.com/jobs/view/example-123",
        "user_agent": jd_fetch.BROWSER_USER_AGENT,
        "accept_encoding": "gzip",
        "timeout": 17,
    }


def test_fetch_full_jd_fails_closed_for_network_and_empty_pages() -> None:
    jd_fetch = load_jd_fetch_module()

    def blocked(_request, timeout):
        raise URLError(f"blocked after {timeout}s")

    blocked_result = jd_fetch.fetch_full_jd(
        "https://www.linkedin.com/jobs/view/blocked",
        opener=blocked,
    )
    empty_result = jd_fetch.fetch_full_jd(
        "https://www.linkedin.com/jobs/view/empty",
        opener=lambda _request, timeout: FakeResponse(b"<html>login wall</html>"),
    )

    assert blocked_result["fetch_method"] == "failed"
    assert blocked_result["jd_text"] == ""
    assert blocked_result["jd_chars"] == 0
    assert "blocked" in blocked_result["fetch_error"]
    assert empty_result == {
        "jd_text": "",
        "jd_chars": 0,
        "fetch_method": "failed",
        "fetch_error": "description not found",
    }


def test_fetch_full_jd_rejects_login_wall_and_malformed_url_without_raising() -> None:
    jd_fetch = load_jd_fetch_module()

    login_wall = jd_fetch.fetch_full_jd(
        "https://www.linkedin.com/jobs/view/login-wall",
        opener=lambda _request, timeout: FakeResponse(
            b'<div class="description__text">Sign in to view the job description.</div>'
        ),
    )
    malformed = jd_fetch.fetch_full_jd("")

    assert login_wall["fetch_method"] == "failed"
    assert login_wall["jd_text"] == ""
    assert login_wall["jd_chars"] == 0
    assert "too short" in login_wall["fetch_error"]
    assert malformed["fetch_method"] == "failed"
    assert malformed["jd_text"] == ""
    assert malformed["jd_chars"] == 0
    assert malformed["fetch_error"]
