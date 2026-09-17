from __future__ import annotations

from pathlib import Path

import psycopg
import pytest

from scripts.backfill_posting_facts import backfill_connection, backfill_database, require_local_database_url
from test_support.postgres import DatabaseUnavailable, migrated_database


ROOT = Path(__file__).parents[1]
MIGRATIONS = ROOT / "supabase/migrations"
POSTING_ID = "00000000-0000-0000-0000-000000015001"


def test_posting_facts_migration_is_rls_service_role_only():
    try:
        with migrated_database(MIGRATIONS, through=15) as url, psycopg.connect(url) as connection:
            assert connection.execute(
                "select relrowsecurity from pg_class where oid='public.posting_facts'::regclass"
            ).fetchone() == (True,)
            assert connection.execute(
                "select relrowsecurity from pg_class where oid='public.location_aliases'::regclass"
            ).fetchone() == (True,)
            assert connection.execute(
                "select has_table_privilege('service_role', 'public.posting_facts', 'select,insert,update,delete')"
            ).fetchone() == (True,)
            assert connection.execute(
                "select not has_table_privilege('anon', 'public.posting_facts', 'select')"
            ).fetchone() == (True,)
            assert connection.execute(
                "select count(*) from pg_trigger where tgrelid='public.posting_facts'::regclass "
                "and not tgisinternal"
            ).fetchone() == (0,)
    except DatabaseUnavailable as error:
        pytest.skip(str(error))


def test_backfill_is_idempotent_and_returns_receipt():
    try:
        with migrated_database(MIGRATIONS, through=15) as url, psycopg.connect(url) as connection:
            connection.execute(
                """insert into public.postings
                   (id, source, external_id, url, title, company, location, remote, seniority, stack)
                   values (%s, 'fixture', 'facts-1', 'https://example.test/job',
                           'Senior Python Engineer', 'Acme', 'Austin, TX', false, null,
                           array['nodejs'])""",
                (POSTING_ID,),
            )
            connection.commit()
            first = backfill_connection(connection, batch_size=1)
            second = backfill_connection(connection, batch_size=1)
            assert first["rows_written"] == 1
            assert second["rows_written"] == 0
            assert second["rows_skipped"] == 1
            assert second["work_mode_counts"] == {"onsite": 1}
            stored = connection.execute(
                "select countries, regions, cities, work_mode, seniority_level, skills_mentioned "
                "from public.posting_facts where posting_id=%s",
                (POSTING_ID,),
            ).fetchone()
            assert stored == (["US"], ["US-TX"], ["Austin"], "onsite", "senior", ["Node.js"])
    except DatabaseUnavailable as error:
        pytest.skip(str(error))


def test_remote_database_is_rejected_before_connect(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:password@db.example.test/jobs")
    monkeypatch.setattr("scripts.backfill_posting_facts.psycopg.connect", lambda *_a, **_k: pytest.fail("connected"))
    with pytest.raises(ValueError, match="localhost or 127.0.0.1"):
        backfill_database()


@pytest.mark.parametrize(
    "database_url",
    [
        "postgresql://user:password@localhost/jobs?host=remote.example",
        "postgresql://user:password@127.0.0.1/jobs?hostaddr=10.0.0.1",
        "postgresql://user:password@localhost/jobs?host=localhost,remote.example",
    ],
)
def test_database_url_rejects_remote_libpq_routing_overrides(monkeypatch, database_url):
    monkeypatch.delenv("PGHOST", raising=False)
    monkeypatch.delenv("PGHOSTADDR", raising=False)
    with pytest.raises(ValueError, match="localhost or 127.0.0.1"):
        require_local_database_url(database_url)


@pytest.mark.parametrize("variable", ["PGHOST", "PGHOSTADDR"])
def test_database_url_rejects_remote_libpq_environment_override(monkeypatch, variable):
    monkeypatch.setenv(variable, "remote.example")
    monkeypatch.delenv("PGHOST" if variable == "PGHOSTADDR" else "PGHOSTADDR", raising=False)
    with pytest.raises(ValueError, match="localhost or 127.0.0.1"):
        require_local_database_url("postgresql://user:password@localhost/jobs")
