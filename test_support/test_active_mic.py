from __future__ import annotations

import threading
import time
from importlib import import_module
from pathlib import Path

import pytest

psycopg = pytest.importorskip("psycopg")
postgres_support = import_module("test_support.postgres")
DatabaseUnavailable = postgres_support.DatabaseUnavailable
migrated_database = postgres_support.migrated_database


ROOT = Path(__file__).parents[1]
MIGRATIONS = ROOT / "supabase/migrations"
MIGRATION = MIGRATIONS / "0009_active_mic.sql"
REGRESSION = ROOT / "supabase/tests/0009_active_mic_test.sql"
CLIENT_A = "00000000-0000-0000-0000-000000009001"
CLIENT_B = "00000000-0000-0000-0000-000000009002"


def test_active_mic_sql_contract() -> None:
    try:
        database = migrated_database(MIGRATIONS, through=9)
        with database as url, psycopg.connect(url) as connection:
            cursor = connection.execute(REGRESSION.read_text(encoding="utf-8"))
            tap = []
            while True:
                if cursor.description:
                    tap.extend(row[0] for row in cursor.fetchall() if isinstance(row[0], str))
                if not cursor.nextset():
                    break
            assert "1..29" in tap
            assert [line for line in tap if line.startswith("not ok")] == []
    except DatabaseUnavailable as error:
        pytest.skip(str(error))


def test_stale_release_serializes_behind_newer_claim() -> None:
    try:
        database = migrated_database(MIGRATIONS, through=9)
        with database as url, psycopg.connect(url) as setup:
            setup.execute("select public.claim_active_mic(%s)", (CLIENT_A,))
            setup.commit()
            with psycopg.connect(url) as claimant, psycopg.connect(url) as releaser:
                claimant.execute("select public.claim_active_mic(%s)", (CLIENT_B,)).fetchone()
                released = []
                errors = []

                def stale_release() -> None:
                    try:
                        releaser.execute("set statement_timeout='5s'")
                        released.append(releaser.execute(
                            "select client_id::text,revision from public.release_active_mic(%s)",
                            (CLIENT_A,),
                        ).fetchone())
                        releaser.commit()
                    except psycopg.Error as error:
                        errors.append(error)

                thread = threading.Thread(target=stale_release)
                thread.start()
                waiting = False
                try:
                    with psycopg.connect(url, autocommit=True) as observer:
                        for _ in range(200):
                            waiting = observer.execute(
                                "select exists(select 1 from pg_locks where pid=%s and not granted)",
                                (releaser.info.backend_pid,),
                            ).fetchone()[0]
                            if waiting:
                                break
                            time.sleep(0.01)
                finally:
                    claimant.commit()
                    thread.join(5)
                assert waiting
                assert not thread.is_alive()
                assert errors == []
                assert released == [(CLIENT_B, 2)]
                assert setup.execute(
                    "select client_id::text,revision from public.get_active_mic()"
                ).fetchone() == (CLIENT_B, 2)
    except DatabaseUnavailable as error:
        pytest.skip(str(error))


def test_migration_requests_postgrest_schema_reload() -> None:
    assert "notify pgrst, 'reload schema';" in MIGRATION.read_text(encoding="utf-8").lower()
