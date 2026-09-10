from __future__ import annotations

from pathlib import Path

import psycopg
import pytest

from test_support.postgres import DatabaseUnavailable, migrated_database

ROOT = Path(__file__).parents[1]
MIGRATIONS = ROOT / "supabase/migrations"
MIGRATION = MIGRATIONS / "0008_list_jobs.sql"
SECURITY_MIGRATION = MIGRATIONS / "0010_hosted_access.sql"
ACTIVE_MIC_MIGRATION = MIGRATIONS / "0009_active_mic.sql"
REGRESSION = ROOT / "supabase/tests/0008_list_jobs_test.sql"


def test_migration_preserves_legacy_function_and_passes_sql_contract() -> None:
    try:
        database = migrated_database(MIGRATIONS, through=7)
        with database as url, psycopg.connect(url) as connection:
            legacy_definition = connection.execute(
                "select pg_get_functiondef('public.list_new_for_me()'::regprocedure)"
            ).fetchone()[0]
            connection.execute(MIGRATION.read_text(encoding="utf-8"))
            connection.commit()
            assert connection.execute(
                "select pg_get_functiondef('public.list_new_for_me()'::regprocedure)"
            ).fetchone()[0] == legacy_definition
            connection.execute(ACTIVE_MIC_MIGRATION.read_text(encoding="utf-8"))
            connection.commit()
            connection.execute(SECURITY_MIGRATION.read_text(encoding="utf-8"))
            connection.commit()
            cursor = connection.execute(REGRESSION.read_text(encoding="utf-8"))
            tap = []
            while True:
                if cursor.description:
                    tap.extend(
                        row[0] for row in cursor.fetchall() if isinstance(row[0], str)
                    )
                if not cursor.nextset():
                    break
            assert "1..24" in tap
            assert [line for line in tap if line.startswith("not ok")] == []
            connection.commit()
    except DatabaseUnavailable as error:
        pytest.skip(str(error))


def test_migration_requests_postgrest_schema_reload() -> None:
    migration = MIGRATION.read_text(encoding="utf-8").lower()
    assert "notify pgrst, 'reload schema';" in migration
