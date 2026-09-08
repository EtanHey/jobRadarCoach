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
BLOCK_TAGS = {"article", "p", "section", "ul", "ol"}
HEADING_TAGS = {f"h{level}": level for level in range(1, 7)}


class _MarkupWriter:
    """Translate only explicit HTML structure into restricted Markdown."""

    def __init__(self) -> None:
        self.parts: list[str] = []
        self.strong_depth = 0
        self.strong_parts: list[str] = []

    def _append(self, value: str) -> None:
        target = self.strong_parts if self.strong_depth else self.parts
        target.append(value)

    def boundary(self, lines: int) -> None:
        self._append("\n" * lines)

    def start(self, tag: str) -> None:
        if tag == "strong":
            if not self.strong_depth:
                self.strong_parts = []
            self.strong_depth += 1
        elif self.strong_depth:
            return
        elif tag in HEADING_TAGS:
            self.boundary(2)
            self.parts.append("#" * HEADING_TAGS[tag] + " ")
        elif tag in BLOCK_TAGS:
            self.boundary(2)
        elif tag == "li":
            self.boundary(1)
            self.parts.append("- ")

    def data(self, value: str) -> None:
        self._append(re.sub(r"\s+", " ", value.replace("\xa0", " ")))

    def br(self) -> None:
        self.boundary(1)

    def end(self, tag: str) -> None:
        if tag == "strong" and self.strong_depth:
            self.strong_depth -= 1
            if not self.strong_depth:
                lines = [re.sub(r"\s+", " ", line).strip()
                         for line in "".join(self.strong_parts).split("\n")]
                self.parts.append("\n".join(f"**{line}**" if line else "" for line in lines))
                self.strong_parts = []
            return
        if self.strong_depth:
            return
        if tag in HEADING_TAGS or tag in BLOCK_TAGS:
            self.boundary(2)
        elif tag == "li":
            self.boundary(1)


class _DescriptionParser(HTMLParser):
    """Capture the preferred JD markup and a broader semantic fallback."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.primary_depth = 0
        self.fallback_depth = 0
        self.primary_tag: str | None = None
        self.fallback_tag: str | None = None
        self.skipped_depth = 0
        self.primary = _MarkupWriter()
        self.fallback = _MarkupWriter()

    def _active_writers(self) -> list[_MarkupWriter]:
        writers = []
        if self.primary_depth:
            writers.append(self.primary)
        if self.fallback_depth:
            writers.append(self.fallback)
        return writers

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

        for writer in self._active_writers():
            writer.br() if tag == "br" else writer.start(tag)

    def handle_data(self, data: str) -> None:
        if not self.skipped_depth:
            for writer in self._active_writers():
                writer.data(data)

    def handle_endtag(self, tag: str) -> None:
        if self.skipped_depth:
            if tag in SKIPPED_TAGS:
                self.skipped_depth = max(0, self.skipped_depth - 1)
            return
        for writer in self._active_writers():
            writer.end(tag)
        if self.primary_depth and tag == self.primary_tag:
            self.primary_depth = max(0, self.primary_depth - 1)
        if self.fallback_depth and tag == self.fallback_tag:
            self.fallback_depth = max(0, self.fallback_depth - 1)


def _normalize(parts: list[str]) -> str:
    text = re.sub(r"[^\S\n]+", " ", "".join(parts).replace("\xa0", " "))
    lines: list[str] = []
    for raw_line in text.split("\n"):
        line = raw_line.strip()
        if line and SHOW_CONTROL_PATTERN.fullmatch(line):
            continue
        if line:
            if line.startswith("- ") and lines[-1:] == [""] and len(lines) > 1:
                if lines[-2].startswith("- "):
                    lines.pop()
            lines.append(line)
        elif lines and lines[-1]:
            lines.append("")
    return "\n".join(lines).strip()


def extract_full_jd(page_html: str) -> str:
    """Extract and normalize the semantic job description from guest-page HTML."""

    if not page_html:
        return ""
    parser = _DescriptionParser()
    parser.feed(page_html)
    parser.close()
    return _normalize(parser.primary.parts) or _normalize(parser.fallback.parts)


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
