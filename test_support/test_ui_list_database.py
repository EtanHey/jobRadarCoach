"""Exercise the real Supabase list builder against a disposable PostgREST/DB."""
import os
from pathlib import Path
import shutil
import socket
import subprocess
import time
from urllib.request import urlopen

import psycopg
import pytest

from test_support.postgres import migrated_database

ROOT = Path(__file__).parents[1]


def test_ui_list_database(tmp_path):
    binary = os.environ.get("JOBRADAR_POSTGREST_BIN") or shutil.which("postgrest")
    if not binary:
        assert os.environ.get("JOBRADAR_REQUIRE_LIST_DB") != "1", "PostgREST is required in CI"
        pytest.skip("PostgREST binary required for the real UI list contract")
    assert (ROOT / "ui/node_modules/tsx").exists(), "npm ci in ui/ is required"
    migrations = ROOT / "supabase/migrations"
    latest = max(int(p.name[:4]) for p in migrations.glob("[0-9][0-9][0-9][0-9]_*.sql"))
    with migrated_database(migrations, through=23) as url:
        with psycopg.connect(url) as db:
            db.execute("""insert into postings(id,source,external_id,url,title,company,raw_jd,first_seen_at,liveness) values
                ('00000000-0000-0000-0000-000000024001','fixture','one','https://example.test/one','Senior Engineer','Fixture','Requirements: 3+ years of backend engineering experience with Python and Docker.','2026-01-01Z','{}'),
                ('00000000-0000-0000-0000-000000024002','fixture','two','https://example.test/two','Engineer','Fixture',null,'2026-01-02Z','{"alive":false}'),
                ('00000000-0000-0000-0000-000000024003','fixture','three','https://example.test/three','Engineer','Fixture',null,'2026-01-01Z','{}')""")
            for migration in sorted(migrations.glob("[0-9][0-9][0-9][0-9]_*.sql")):
                if 23 < int(migration.name[:4]) <= latest:
                    db.execute(migration.read_text())
            db.execute("insert into posting_status(posting_id,status) select id,case when external_id='two' then 'seen' else 'new' end from postings")
        with psycopg.connect(url) as db:
            db.execute("update postings set raw_jd='Requirements: 4 years of software engineering experience with React', stack=array['Extracted'] where external_id='three'")
            metadata = db.execute("select list_metadata from postings where external_id='three'").fetchone()[0]
            assert metadata == {'experience': '4 years of software engineering experience', 'stack': ['React'], 'description_available': True}
            db.execute("update postings set raw_jd=null, stack=array['Extracted'] where external_id='three'")
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0))
            port = sock.getsockname()[1]
        env = {**os.environ, 'PGRST_DB_URI': url, 'PGRST_DB_SCHEMAS': 'public', 'PGRST_DB_ANON_ROLE': 'service_role', 'PGRST_SERVER_HOST': '127.0.0.1', 'PGRST_SERVER_PORT': str(port), 'PGRST_DB_CONFIG': 'false', 'GHCRTS': '-N2'}
        with (tmp_path / 'postgrest.log').open('w') as log:
            process = subprocess.Popen([binary], env=env, stdout=log, stderr=log)
            try:
                endpoint = f'http://127.0.0.1:{port}'
                for _ in range(100):
                    assert process.poll() is None, "disposable PostgREST exited"
                    try:
                        with urlopen(endpoint, timeout=1):
                            break
                    except OSError:
                        time.sleep(0.05)
                else:
                    pytest.fail('disposable PostgREST did not become ready')
                subprocess.run(['node','--conditions=react-server','--import','tsx','--test','db-tests/list.test.ts'], cwd=ROOT / 'ui', env={**os.environ,'JOBRADAR_TEST_REST_URL':endpoint}, check=True, timeout=60)
            finally:
                process.terminate()
                process.wait(timeout=10)
