"""Publication migration, legacy-writer protection and SQL consumer proof."""
from pathlib import Path

import psycopg
import pytest

from test_support.postgres import DatabaseUnavailable, migrated_database

MIGRATIONS = Path(__file__).parents[1] / "supabase/migrations"


def test_publication_upgrade_preserves_history_and_sql_projections():
    try:
        with migrated_database(MIGRATIONS, through=18) as url, psycopg.connect(url) as db:
            [posting_id] = db.execute("""insert into postings
                (source, external_id, url, title, company, posted_at, first_seen_at)
                values ('fixture','dates','https://example.test','Engineer','Fixture',
                        '2026-09-01Z','2026-09-02Z') returning id""").fetchone()
            db.execute((MIGRATIONS / "0019_publication_dates.sql").read_text())
            assert db.execute("select last_published_at = posted_at from postings where id=%s", (posting_id,)).fetchone() == (True,)
            # The old scraper still assigns incoming posted_at; the database must guard it.
            db.execute("update postings set posted_at='2026-10-01Z' where id=%s", (posting_id,))
            for projection in ["postings where id=%s", "get_job(%s)", "_job_card(%s)"]:
                assert db.execute(f"select posted_at::text, last_published_at::text, first_seen_at::text from {projection}", (posting_id,)).fetchone() == (
                    "2026-09-01 00:00:00+00", "2026-10-01 00:00:00+00", "2026-09-02 00:00:00+00")
            assert db.execute("select last_published_at::text from search_jobs(null)").fetchone() == ("2026-10-01 00:00:00+00",)
            snapshot = db.execute("select get_globe_snapshot('all','all')").fetchone()[0]
            assert snapshot["jobs"][0]["last_published_at"].startswith("2026-10-01")
            db.execute("update postings set posted_at=null, last_published_at='2026-08-01Z' where id=%s", (posting_id,))
            assert db.execute("select posted_at::text, last_published_at::text from postings where id=%s", (posting_id,)).fetchone() == (
                "2026-09-01 00:00:00+00", "2026-10-01 00:00:00+00")
    except DatabaseUnavailable as error:
        pytest.skip(str(error))
