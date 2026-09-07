#!/usr/bin/env python3
"""Fetch complete LinkedIn job descriptions from public guest pages."""

from __future__ import annotations

import gzip
import re
from html.parser import HTMLParser
from typing import Callable
from urllib.request import Request, urlopen


BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/138.0.0.0 Safari/537.36"
)
MIN_PLAUSIBLE_JD_CHARS = 200
SKIPPED_TAGS = {"button", "script", "style", "svg"}
SHOW_CONTROL_PATTERN = re.compile(r"^Show\s+(?:more|less)$", re.IGNORECASE)


class _DescriptionParser(HTMLParser):
    """Capture the preferred JD markup and a broader semantic fallback."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.primary_depth = 0
        self.fallback_depth = 0
        self.primary_tag: str | None = None
        self.fallback_tag: str | None = None
        self.skipped_depth = 0
        self.primary_parts: list[str] = []
        self.fallback_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in SKIPPED_TAGS:
            self.skipped_depth += 1
            return
        if self.skipped_depth:
            return

        attributes = {key: value or "" for key, value in attrs}
        classes = set(attributes.get("class", "").split())

        if self.primary_depth:
            if tag == self.primary_tag:
                self.primary_depth += 1
        elif "show-more-less-html__markup" in classes:
            self.primary_depth = 1
            self.primary_tag = tag

        if self.fallback_depth:
            if tag == self.fallback_tag:
                self.fallback_depth += 1
        elif "description__text" in classes:
            self.fallback_depth = 1
            self.fallback_tag = tag

        if tag == "br":
            if self.primary_depth:
                self.primary_parts.append("\n")
            if self.fallback_depth:
                self.fallback_parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.skipped_depth and self.primary_depth:
            self.primary_parts.append(data)
        if not self.skipped_depth and self.fallback_depth:
            self.fallback_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if self.skipped_depth:
            if tag in SKIPPED_TAGS:
                self.skipped_depth = max(0, self.skipped_depth - 1)
            return
        if self.primary_depth and tag == self.primary_tag:
            self.primary_depth = max(0, self.primary_depth - 1)
        if self.fallback_depth and tag == self.fallback_tag:
            self.fallback_depth = max(0, self.fallback_depth - 1)


def _normalize(parts: list[str]) -> str:
    visible_parts = [part for part in parts if not SHOW_CONTROL_PATTERN.fullmatch(part.strip())]
    text = " ".join(visible_parts).replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip()


def extract_full_jd(page_html: str) -> str:
    """Extract and normalize the semantic job description from guest-page HTML."""

    if not page_html:
        return ""
    parser = _DescriptionParser()
    parser.feed(page_html)
    parser.close()
    return _normalize(parser.primary_parts) or _normalize(parser.fallback_parts)


def _failed(error: object) -> dict[str, object]:
    return {
        "jd_text": "",
        "jd_chars": 0,
        "fetch_method": "failed",
        "fetch_error": str(error),
    }


def fetch_full_jd(
    url: str,
    *,
    opener: Callable[..., object] = urlopen,
    timeout: int = 20,
) -> dict[str, object]:
    """Fetch one public guest page and return a fail-closed result dictionary."""

    try:
        request = Request(
            url,
            headers={
                "User-Agent": BROWSER_USER_AGENT,
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Encoding": "gzip",
                "Accept-Language": "en-US,en;q=0.9",
            },
        )
        timeout = min(timeout, 30)
        with opener(request, timeout=timeout) as response:
            body = response.read()
            headers = response.headers
            if str(headers.get("Content-Encoding", "")).casefold() == "gzip":
                body = gzip.decompress(body)
            charset = headers.get_content_charset() or "utf-8"
            page_html = body.decode(charset, errors="replace")
        description = extract_full_jd(page_html)
        if not description:
            return _failed("description not found")
        if len(description) < MIN_PLAUSIBLE_JD_CHARS:
            return _failed(
                f"description too short ({len(description)} chars; "
                f"minimum {MIN_PLAUSIBLE_JD_CHARS})"
            )
        return {
            "jd_text": description,
            "jd_chars": len(description),
            "fetch_method": "guest-html",
            "fetch_error": None,
        }
    except Exception as error:
        return _failed(error)
