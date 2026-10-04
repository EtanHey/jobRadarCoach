"""Exercise every SQL contract and the latest schema on a disposable database."""

import os
from pathlib import Path

import psycopg
import pytest

from test_support.postgres import DatabaseUnavailable, database_url, migrated_database
from test_support.tap import assert_tap

ROOT = Path(__file__).parents[1]
MIGRATIONS = ROOT / "supabase/migrations"
CONTRACTS = sorted((ROOT / "supabase/tests").glob("*.sql"))
LATEST = max(int(path.name[:4]) for path in MIGRATIONS.glob("[0-9][0-9][0-9][0-9]_*.sql"))


@pytest.fixture(scope="module", autouse=True)
def require_database():
    try:
        database_url()
    except DatabaseUnavailable as error:
        if os.environ.get("JOBRADAR_REQUIRE_PG17") == "1":
            pytest.fail(str(error))
        pytest.skip(str(error))


def test_latest_migrations_apply():
    assert CONTRACTS, "No SQL contracts discovered"
    with migrated_database(MIGRATIONS, through=LATEST) as url, psycopg.connect(url) as db:
        if os.environ.get("JOBRADAR_REQUIRE_PG17") == "1":
            assert db.info.server_version // 10000 == 17
            assert db.execute("show timezone").fetchone() == ("UTC",)
        roles = dict(db.execute(
            "select rolname, rolbypassrls from pg_roles where rolname = any(%s)",
            (["anon", "authenticated", "service_role", "supabase_realtime_admin"],),
        ).fetchall())
        assert set(roles) == {"anon", "authenticated", "service_role", "supabase_realtime_admin"}
        assert roles["service_role"] is True
        db.execute("create extension pgtap")


@pytest.mark.parametrize("contract", CONTRACTS, ids=lambda path: path.name)
def test_sql_contract(contract):
    # Numbered contract files include assertions updated by later migrations.
    with migrated_database(MIGRATIONS, through=LATEST) as url:
        with psycopg.connect(url, autocommit=True) as db:
            cursor = db.execute(contract.read_text(encoding="utf-8"))
            output = []
            while True:
                if cursor.description:
                    output.extend(row[0] for row in cursor.fetchall() if isinstance(row[0], str))
                if not cursor.nextset():
                    break
            assert_tap(output)
