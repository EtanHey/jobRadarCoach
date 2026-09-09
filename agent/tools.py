import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import UUID

from db import pool

JOB_LOOKUP_FAILED = "The job lookup failed. I can't recommend a job right now."
NO_MORE_JOBS = "That's every scored unseen job I loaded for this conversation."
NO_STRONG_JOBS = (
    "I didn't load a new match above seventy. Ask for more options if you want to hear "
    "the lower-scored ones."
)
NO_FILTERED_JOBS = "I didn't find any unseen jobs matching those filters."
_logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class JobFilters:
    location: str | None = None
    seniority: str | None = None
    min_score: int | None = None
    query: str | None = None
    remote: bool | None = None

    def merged(self, updates: dict[str, object]) -> "JobFilters":
        values = self.as_log_fields()
        values.update(updates)
        return JobFilters(**values)

    def as_log_fields(self) -> dict[str, object]:
        return {
            "location": self.location,
            "seniority": self.seniority,
            "min_score": self.min_score,
            "query": self.query,
            "remote": self.remote,
        }


@dataclass(frozen=True)
class Posting:
    id: UUID
    title: str
    company: str
    location: str
    score: int
    reasons: str
    apply_url: str

    def as_log_row(self) -> dict[str, object]:
        return {
            "id": str(self.id),
            "title": self.title,
            "company": self.company,
            "location": self.location,
            "score": self.score,
            "reasons": self.reasons,
            "apply_url": self.apply_url,
        }

    def grounded_context(self) -> str:
        return json.dumps(self.as_log_row(), ensure_ascii=False)


@dataclass
class SessionState:
    discussed_posting_ids: set[UUID] = field(default_factory=set)
    candidates: tuple[Posting, ...] = ()
    cursor: int = -1
    lookup_error: str | None = None
    current_posting: Posting | None = None
    turn_posting: Posting | None = None
    deterministic_reply: str | None = None
    intent_failed: bool = False
    intended_text: str | None = None
    qa_mode: bool = False
    prepared_message_id: str | None = None
    filters: JobFilters = field(default_factory=JobFilters)
    allow_more_options: bool = False
    search_widened: bool = False

    def load_candidates(self, candidates: list[Posting]) -> None:
        self.candidates = tuple(candidates)

    def replace_candidates(
        self, candidates: list[Posting], *, filters: JobFilters
    ) -> None:
        self.candidates = tuple(p for p in candidates if p.id not in self.discussed_posting_ids)
        self.cursor = -1
        self.lookup_error = None
        self.current_posting = None
        self.turn_posting = None
        self.filters = filters

    def fail_lookup(self) -> None:
        self.lookup_error = JOB_LOOKUP_FAILED
        self.candidates = ()
        self.current_posting = None
        self.turn_posting = None
        self.cursor = -1

    def advance(self, *, strong_only: bool = False) -> Posting | None:
        next_cursor = self.cursor + 1
        if (
            strong_only
            and next_cursor < len(self.candidates)
            and self.candidates[next_cursor].score <= 70
        ):
            return None
        self.cursor += 1
        self.current_posting = (
            self.candidates[self.cursor] if self.cursor < len(self.candidates) else None
        )
        return self.current_posting

    def observe_delivery(self, spoken_text: str, *, interrupted: bool) -> None:
        posting = self.current_posting
        if posting is None or interrupted:
            return
        normalized = spoken_text.casefold()
        if (
            posting.title.casefold() in normalized
            and posting.company.casefold() in normalized
        ):
            self.discussed_posting_ids.add(posting.id)


async def owner_state_fingerprint() -> dict[str, object]:
    """Read-only QA receipt for the owner-controlled tables."""
    db_pool = await pool()
    async with db_pool.acquire() as conn:
        transaction_read_only = await conn.fetchval("show transaction_read_only")
        owner_rows = {}
        for table_name in ("posting_status", "profile", "active_mic"):
            # Fixed identifiers only. Hash complete rows so schema additions cannot
            # silently fall outside the QA mutation witness.
            owner_rows[table_name] = await conn.fetch(
                f"select to_jsonb(owner_row) as value from {table_name} owner_row"
            )

    def digest(rows: list[object]) -> dict[str, object]:
        canonical_rows = sorted(
            json.dumps(
                row["value"],
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            )
            for row in rows
        )
        payload = json.dumps(
            canonical_rows,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode()
        return {"count": len(rows), "sha256": hashlib.sha256(payload).hexdigest()}

    return {
        "database_transaction_read_only": transaction_read_only == "on",
        **{table_name: digest(rows) for table_name, rows in owner_rows.items()},
    }


def _format_reasons(reasons: object) -> str:
    if not isinstance(reasons, list):
        return ""
    details: list[str] = []
    for reason in reasons:
        if not isinstance(reason, dict):
            continue
        detail = reason.get("detail")
        if not isinstance(detail, str) or not detail.strip():
            continue
        cleaned = detail.strip()
        if cleaned not in details:
            details.append(cleaned)
    return " ".join(details)


async def list_new_for_me(
    *,
    limit: int,
    min_score: int,
    excluded_ids: set[UUID],
) -> list[Posting]:
    """Load the ranked session candidate set once; the model never invokes this."""
    arguments = {
        "limit": limit,
        "min_score": min_score,
        "excluded_ids": [
            str(posting_id) for posting_id in sorted(excluded_ids, key=str)
        ],
    }
    started_at = datetime.now(timezone.utc).isoformat()
    started = time.perf_counter()
    _logger.info(
        "tool invocation started",
        extra={
            "tool_name": "list_new_for_me",
            "arguments": arguments,
            "start_time": started_at,
        },
    )
    try:
        rows = await (await pool()).fetch(
            """
            select p.id, p.title, p.company, coalesce(p.location, '') as location,
                   s.score, s.reasons,
                   coalesce(nullif(p.apply_url, ''), p.url) as apply_url
            from postings p
            join posting_scores s on s.posting_id = p.id
            join posting_status st on st.posting_id = p.id
            where st.status = 'new'
              and s.score >= $2
              and coalesce(nullif(p.apply_url, ''), p.url) is not null
              and not (p.id = any($3::uuid[]))
            order by s.score desc, p.posted_at desc nulls last, p.id
            limit $1
            """,
            limit,
            min_score,
            list(excluded_ids),
        )
        postings = [
            Posting(
                id=row["id"],
                title=row["title"],
                company=row["company"],
                location=row["location"],
                score=row["score"],
                reasons=_format_reasons(row["reasons"]),
                apply_url=row["apply_url"],
            )
            for row in rows
        ]
        _logger.info(
            "tool invocation completed",
            extra={
                "tool_name": "list_new_for_me",
                "arguments": arguments,
                "start_time": started_at,
                "duration_ms": round((time.perf_counter() - started) * 1000, 3),
                "outcome": "success" if postings else "empty",
                "returned_rows": [posting.as_log_row() for posting in postings],
            },
        )
        return postings
    except Exception:
        _logger.exception(
            "tool invocation failed",
            extra={
                "tool_name": "list_new_for_me",
                "arguments": arguments,
                "start_time": started_at,
                "duration_ms": round((time.perf_counter() - started) * 1000, 3),
                "outcome": "exception",
            },
        )
        raise


async def list_jobs(
    *,
    limit: int,
    filters: JobFilters,
    excluded_ids: set[UUID],
) -> list[Posting]:
    """Re-query ranked unseen jobs with code-validated session filters."""
    if not 1 <= limit <= 1000:
        raise ValueError("limit must be between 1 and 1000")
    if filters.min_score is not None and not 0 <= filters.min_score <= 100:
        raise ValueError("min_score must be between 0 and 100")

    # public.list_jobs has no remote argument. Fetch its bounded ranked result and
    # apply the boolean projection in code so "remote" means the stored remote
    # field, not a guess based only on location text.
    fetch_limit = min(1000, limit + len(excluded_ids))
    if filters.remote is not None:
        fetch_limit = 1000
    arguments = {
        "seen": False,
        "max": fetch_limit,
        **filters.as_log_fields(),
        "excluded_ids": [
            str(posting_id) for posting_id in sorted(excluded_ids, key=str)
        ],
    }
    started_at = datetime.now(timezone.utc).isoformat()
    started = time.perf_counter()
    _logger.info(
        "tool invocation started",
        extra={
            "tool_name": "list_jobs",
            "arguments": arguments,
            "start_time": started_at,
        },
    )
    try:
        rows = await (await pool()).fetch(
            """
            select posting_id, title, company, coalesce(location, '') as location,
                   remote, score, reasons, coalesce(nullif(apply_url, ''), url) as apply_url
            from public.list_jobs(false, $1, $2, $3, $4, $5)
            """,
            fetch_limit,
            filters.min_score,
            filters.location,
            filters.seniority,
            filters.query,
        )
        postings = [
            Posting(
                id=row["posting_id"],
                title=row["title"],
                company=row["company"],
                location=row["location"],
                score=row["score"],
                reasons=_format_reasons(row["reasons"]),
                apply_url=row["apply_url"],
            )
            for row in rows
            if row["posting_id"] not in excluded_ids
            and row["score"] is not None
            and row["apply_url"]
            and (filters.remote is None or row["remote"] is filters.remote)
        ][:limit]
        _logger.info(
            "tool invocation completed",
            extra={
                "tool_name": "list_jobs",
                "arguments": arguments,
                "start_time": started_at,
                "duration_ms": round((time.perf_counter() - started) * 1000, 3),
                "outcome": "success" if postings else "empty",
                "returned_rows": [posting.as_log_row() for posting in postings],
            },
        )
        return postings
    except Exception:
        _logger.exception(
            "tool invocation failed",
            extra={
                "tool_name": "list_jobs",
                "arguments": arguments,
                "start_time": started_at,
                "duration_ms": round((time.perf_counter() - started) * 1000, 3),
                "outcome": "exception",
            },
        )
        raise
