"""Shared rollback-isolated database fixtures for this package."""
from pathlib import Path

import pytest

psycopg = pytest.importorskip("psycopg")
from test_support.postgres import DatabaseUnavailable, migrated_database

MIGRATIONS = Path(__file__).parents[1] / "supabase/migrations"


@pytest.fixture(scope="module")
def migrated_database_url():
    try:
        with migrated_database(MIGRATIONS, through=28) as url:
            yield url
    except DatabaseUnavailable as error:
        pytest.skip(str(error))


@pytest.fixture
def connection(migrated_database_url):
    connection = psycopg.connect(migrated_database_url)
    connection.execute("select 1")
    try:
        yield connection
    finally:
        connection.rollback()
        connection.close()

