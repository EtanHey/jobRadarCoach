"""Anonymous Workable Markdown-board adapter."""

from __future__ import annotations

import logging
import re
from typing import Callable


DETAIL_PATTERN = re.compile(
    r"\[View\]\(https://apply\.workable\.com/[^/]+/jobs/view/([A-Z0-9]+)\.md\)"
)
LOGGER = logging.getLogger("coach.jobfeed.source.workable")


def _board_rows(markdown: str) -> list[tuple[str, str, str, str]]:
    rows: list[tuple[str, str, str, str]] = []
    for line in markdown.splitlines():
        match = DETAIL_PATTERN.search(line)
        if match is None:
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) != 7:
            continue
        rows.append((cells[0], cells[2], cells[5], match.group(1)))
    return rows


def fetch(
    query: dict[str, str],
    *,
    fetcher: Callable[[str], str | None],
    before_request: Callable[[], None],
    posting_filter: Callable[[dict[str, object]], bool] | None = None,
) -> list[dict[str, object]]:
    account = query["account"]
    company = query.get("company", account)
    before_request()
    board = fetcher(f"https://apply.workable.com/{account}/jobs.md")
    if board is None:
        raise RuntimeError("Workable board request failed")

    postings: list[dict[str, object]] = []
    rows = _board_rows(board)
    filtered_count = 0
    for title, location, posted_date, token in rows:
        url = f"https://apply.workable.com/{account}/jobs/view/{token}.md"
        posting = {
            "id": f"workable:{account}:{token}",
            "title": title,
            "company": company,
            "location": location,
            "url": url,
            "posted_at": f"{posted_date}T00:00:00Z",
            "posted_ago": posted_date,
            "source": "workable",
            "raw_text": " ".join(value for value in (title, company, location) if value),
        }
        if posting_filter is not None and not posting_filter(posting):
            filtered_count += 1
            continue
        before_request()
        jd_text = fetcher(url) or ""
        posting["jd_fetched"] = bool(jd_text.strip())
        posting["jd_text"] = jd_text.strip()
        postings.append(posting)
    if filtered_count:
        LOGGER.info(
            "Filtered %d of %d workable postings before detail fetch",
            filtered_count,
            len(rows),
        )
    return postings
