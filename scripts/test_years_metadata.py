"""Focused SQL parity against real, temporary local PostgreSQL; never Docker or hosted DBs."""

import json
import os
from pathlib import Path
import subprocess
import tempfile

import pytest

ROOT = Path(__file__).resolve().parents[1]
CASES = json.loads((ROOT / "ui/tests/fixtures/years-extraction.json").read_text())


@pytest.fixture(scope="module")
def years_sql():
    bindir = Path("/opt/homebrew/opt/postgresql@16/bin")
    if not (bindir / "initdb").exists():
        pytest.skip("local PostgreSQL 16 binaries unavailable; Docker is forbidden")
    import psycopg

    with tempfile.TemporaryDirectory(prefix="jrc-years-") as folder:
        data, sock = Path(folder) / "data", Path(folder) / "sock"
        sock.mkdir()
        subprocess.run([bindir / "initdb", "-D", data, "-A", "trust", "--no-locale", "-E", "UTF8"], check=True, capture_output=True)
        subprocess.run([bindir / "pg_ctl", "-D", data, "-l", Path(folder) / "postgres.log", "-o", f"-F -k {sock} -h ''", "-w", "start"], check=True, capture_output=True)
        try:
            with psycopg.connect(host=str(sock), dbname="postgres", user=os.environ.get("USER"), autocommit=True) as connection:
                original = (ROOT / "supabase/migrations/0024_list_metadata.sql").read_text()
                function = original[original.index("create function"):original.index("revoke all")]
                connection.execute(function)
                connection.execute("create role anon; create role authenticated; create role service_role")
                connection.execute((ROOT / "supabase/migrations/0039_years_metadata.sql").read_text())
                migration = ROOT / "supabase/migrations/0040_years_compact_formats.sql"
                connection.execute(migration.read_text())
                before = [connection.execute("select public.posting_list_metadata(%s)", (description,)).fetchone()[0]
                          for description, _ in CASES]
                connection.execute(migration.read_text())
                after = [connection.execute("select public.posting_list_metadata(%s)", (description,)).fetchone()[0]
                         for description, _ in CASES]
                assert after == before
                yield connection
        finally:
            subprocess.run([bindir / "pg_ctl", "-D", data, "-m", "fast", "-w", "stop"], check=True, capture_output=True)


@pytest.mark.parametrize("description,expected", CASES)
def test_sql_years_quotes(years_sql, description, expected):
    actual = years_sql.execute("select public.posting_list_metadata(%s)->>'experience'", (description,)).fetchone()[0]
    assert actual == expected


def test_sql_matches_typescript_metadata_corpus(years_sql):
    corpus = json.loads((ROOT / "ui/db-tests/fixtures/metadata-corpus.json").read_text())
    source = "import {experiencePhrase,technologyMentions} from './lib/job-metadata.ts'; import corpus from './db-tests/fixtures/metadata-corpus.json'; console.log(JSON.stringify(corpus.map(description=>({experience:experiencePhrase(description),stack:technologyMentions(description),description_available:Boolean(description?.trim())}))));"
    result = subprocess.run(["node", "--import", "tsx", "--input-type=module", "-e", source], cwd=ROOT / "ui", check=True, capture_output=True, text=True)
    for description, expected in zip(corpus, json.loads(result.stdout), strict=True):
        actual = years_sql.execute("select public.posting_list_metadata(%s)", (description,)).fetchone()[0]
        assert actual == expected, description


def test_generated_migration_is_current():
    from scripts.generate_years_metadata import generate

    assert (ROOT / "supabase/migrations/0040_years_compact_formats.sql").read_text() == generate()
