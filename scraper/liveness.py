"""Bounded, deterministic liveness checks for public job URLs."""

from __future__ import annotations

import html
import re
from datetime import datetime, timezone
from typing import Callable
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36"
)
DEAD_STATUS_CODES = {404, 410}
DEAD_TEXT = re.compile(
    r"\b(?:no longer accepting applications|job (?:is )?no longer available|"
    r"position (?:has been|is) (?:filled|closed)|this job has expired)\b",
    re.I,
)
SEARCH_PATH = re.compile(r"/(?:jobs/)?search(?:/|$)|/search/results/jobs", re.I)
AUTH_PATH = re.compile(r"/(?:authwall|uas/login|login|checkpoint)(?:/|$)", re.I)
# Modern ATS pages ship a hydration blob (``__NEXT_DATA__``, ``window.__APP_STATE__``)
# carrying every i18n string, including the closed-job banner a LIVE page never shows.
# Scanning it would mark applyable jobs dead, so script/style content is removed before
# the visible-text pass. Only the text test sees the stripped body; storage is untouched.
NON_VISIBLE_MARKUP = re.compile(
    r"<(script|style)\b[^>]*>.*?</\1\s*>", re.I | re.S
)


def _visible_text(body: str) -> str:
    """Return the human-visible text of ``body`` with script/style content removed."""

    without_code = NON_VISIBLE_MARKUP.sub(" ", body)
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", without_code)).split())


def _checked_at() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def _result(
    alive: bool | None,
    *,
    status: int | None,
    reason: str,
    final_url: str,
) -> dict[str, object]:
    return {
        "alive": alive,
        "liveness_status": status,
        "liveness_reason": reason,
        "liveness_final_url": final_url,
        "liveness_checked_at": _checked_at(),
    }


def _redirected_to_search(original_url: str, final_url: str) -> bool:
    if original_url == final_url:
        return False
    final = urlparse(final_url)
    return bool(SEARCH_PATH.search(final.path))


def _redirected_to_auth(original_url: str, final_url: str) -> bool:
    return original_url != final_url and bool(AUTH_PATH.search(urlparse(final_url).path))


def _error_final_url(error: HTTPError, requested_url: str) -> str:
    """Final URL an ``HTTPError`` was raised for, across interpreter versions.

    ``urlopen`` raises on 4xx, so the success-path auth check never sees a real
    authwall (401/403/404). Recovering the post-redirect URL here is what makes
    the auth guard reachable. On Python 3.9 ``HTTPError.url`` is only defined when
    ``fp`` is not None; otherwise the attribute lookup raises ``KeyError`` from the
    tempfile wrapper, which ``getattr(..., default)`` does NOT absorb. ``filename``
    is set unconditionally in ``__init__``, so it is the portable fallback.
    """

    for attribute in ("url", "filename"):
        try:
            candidate = getattr(error, attribute)
        except Exception:  # noqa: BLE001 - 3.9 raises KeyError, not AttributeError
            continue
        if isinstance(candidate, str) and candidate:
            return candidate
    return requested_url


def check_url(
    url: str,
    *,
    opener: Callable[..., object] = urlopen,
    timeout: float = 12.0,
) -> dict[str, object]:
    """Return conclusive live/dead state, or ``alive=None`` for uncertainty."""

    if not urlparse(url).scheme.startswith("http"):
        return _result(None, status=None, reason="invalid-url", final_url=url)

    headers = {"User-Agent": BROWSER_USER_AGENT, "Accept": "text/html,*/*"}
    try:
        get = Request(url, headers=headers, method="GET")
        with opener(get, timeout=timeout) as response:
            status = int(response.getcode())
            final_url = str(response.geturl())
            body = response.read(512_000).decode("utf-8", errors="replace")
        if status in DEAD_STATUS_CODES:
            return _result(False, status=status, reason=f"http-{status}", final_url=final_url)
        if _redirected_to_auth(url, final_url):
            return _result(None, status=status, reason="redirect-to-auth", final_url=final_url)
        if _redirected_to_search(url, final_url):
            return _result(False, status=status, reason="redirect-to-search", final_url=final_url)
        if DEAD_TEXT.search(_visible_text(body)):
            return _result(False, status=status, reason="closed-page-text", final_url=final_url)
        return _result(True, status=status, reason="http-live", final_url=final_url)
    except HTTPError as error:
        final_url = _error_final_url(error, url)
        if AUTH_PATH.search(urlparse(final_url).path):
            return _result(
                None, status=error.code, reason="redirect-to-auth", final_url=final_url
            )
        if error.code in DEAD_STATUS_CODES:
            return _result(
                False, status=error.code, reason=f"http-{error.code}", final_url=final_url
            )
        return _result(
            None,
            status=error.code,
            reason=f"http-{error.code}-uncertain",
            final_url=final_url,
        )
    except OSError as error:
        return _result(
            None,
            status=None,
            reason=f"network-uncertain:{type(error).__name__}",
            final_url=url,
        )


def check_posting(posting: dict[str, object]) -> dict[str, object]:
    return check_url(str(posting.get("url", "")))
