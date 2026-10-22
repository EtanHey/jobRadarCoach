"""Deadline metadata round trips through real rollback-isolated PostgreSQL."""
import json
from datetime import datetime, timezone

from extractor.persistence import persist_extraction
from extractor.test_persistence import RAW_JD, extraction, insert_posting
from scraper.ats_liveness import project_liveness
from scraper.deadlines import extract_deadline


def test_deadline_preserves_page_history_and_survives_unchanged_extraction(connection):
    raw = RAW_JD + "\nApplications close on October 18th, 2026."
    posting_id = insert_posting(connection, raw)
    assert persist_extraction(connection, posting_id, raw, extraction(raw)) == "stored"
    stored = connection.execute("select liveness from postings where id=%s", (posting_id,)).fetchone()[0]
    assert stored == {"alive": True, **extract_deadline(raw)}
    assert project_liveness(stored, now=datetime(2026, 10, 22, tzinfo=timezone.utc))["alive"] is False
    # Legacy LLM receipt already matches, but deterministic deadline data is missing.
    connection.execute("update postings set liveness='{}'::jsonb where id=%s", (posting_id,))
    assert persist_extraction(connection, posting_id, raw, extraction(raw)) == "unchanged"
    assert connection.execute("select liveness from postings where id=%s", (posting_id,)).fetchone()[0] == extract_deadline(raw)


def test_removed_and_unparseable_deadlines_clear_only_parser_owned_metadata(connection):
    raw = RAW_JD + "\nApplication deadline: 2026-10-18"
    posting_id = insert_posting(connection, raw)
    persist_extraction(connection, posting_id, raw, extraction(raw))
    replacement = RAW_JD + "\nApplication deadline: October 25th"
    connection.execute("update postings set raw_jd=%s where id=%s", (replacement, posting_id))
    persist_extraction(connection, posting_id, replacement, extraction(replacement))
    stored = connection.execute("select liveness from postings where id=%s", (posting_id,)).fetchone()[0]
    assert stored == {"alive": True, **extract_deadline(replacement)}
    connection.execute("update postings set raw_jd=%s where id=%s", (RAW_JD, posting_id))
    persist_extraction(connection, posting_id, RAW_JD, extraction())
    assert connection.execute("select liveness from postings where id=%s", (posting_id,)).fetchone()[0] == {"alive": True, **extract_deadline(RAW_JD)}


def test_stale_capture_cannot_change_deadline_and_unowned_deadline_is_preserved(connection):
    posting_id = insert_posting(connection)
    manual = {"alive": True, "application_deadline": "2026-11-01T17:00:00Z"}
    connection.execute("update postings set liveness=%s::jsonb where id=%s", (json.dumps(manual), posting_id))
    stale = RAW_JD + "\nApplication deadline: 2026-10-18"
    assert persist_extraction(connection, posting_id, stale, extraction(stale)) == "stale"
    assert persist_extraction(connection, posting_id, RAW_JD, extraction()) == "stored"
    assert connection.execute("select liveness from postings where id=%s", (posting_id,)).fetchone()[0] == manual
