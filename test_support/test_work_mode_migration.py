"""Work-mode upgrade preserves publication projections and atomic rollback."""
import json
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest

from scripts.job_api_contract import contract_for_connection
from test_support.postgres import migrated_database

MIGRATIONS = Path(__file__).parents[1] / 'supabase/migrations'
MIGRATION = MIGRATIONS / '0020_posting_work_mode.sql'
SNAPSHOT = MIGRATIONS.parent / 'contracts/job_api.json'


@pytest.mark.parametrize('through', [19, 20])
def test_fresh_chain_and_existing_publication_schema_upgrade(through):
    with migrated_database(MIGRATIONS, through=through) as url, psycopg.connect(url, autocommit=True) as db:
        identity = uuid4()
        db.execute("insert into postings(id,source,external_id,url,title,company,posted_at,last_published_at) "
                   "values(%s,'migration','fixture','https://example.test/job','Engineer','Example',"
                   "'2026-09-01Z','2026-10-01Z')", (identity,))
        if through == 19:
            db.execute(MIGRATION.read_text())
        assert db.execute('select work_mode,work_mode_source from postings where id=%s', (identity,)).fetchone() == (None, None)
        db.execute("update postings set work_mode='hybrid',work_mode_source='location' where id=%s", (identity,))
        assert contract_for_connection(db) == json.loads(SNAPSHOT.read_text())
        assert db.execute('select work_mode,posted_at::text,last_published_at::text from get_job(%s)', (identity,)).fetchone() == ('hybrid', '2026-09-01 00:00:00+00', '2026-10-01 00:00:00+00')
        assert db.execute('select work_mode from search_jobs(seen=>null)').fetchone() == ('hybrid',)
        assert db.execute('select get_globe_snapshot()').fetchone()[0]['jobs'][0]['work_mode'] == 'hybrid'


def test_failed_ddl_rolls_back_columns_types_and_allows_retry():
    with migrated_database(MIGRATIONS, through=19) as url, psycopg.connect(url, autocommit=True) as db:
        before = contract_for_connection(db)
        ddl_prefix = MIGRATION.read_text().split('create or replace function public._job_card', 1)[0]
        db.execute(ddl_prefix)
        with pytest.raises(psycopg.errors.DivisionByZero):
            db.execute('select 1 / 0')
        db.rollback()
        assert db.execute("select count(*) from information_schema.columns where table_schema='public' "
                          "and table_name='postings' and column_name in ('work_mode','work_mode_source')").fetchone() == (0,)
        assert contract_for_connection(db) == before
        db.execute(MIGRATION.read_text())
        assert db.execute("select work_mode from get_job('00000000-0000-0000-0000-000000000000')").fetchone() is None


def test_documented_rollback_restores_publication_contract():
    with migrated_database(MIGRATIONS, through=19) as url, psycopg.connect(url, autocommit=True) as db:
        before = contract_for_connection(db)
        db.execute(MIGRATION.read_text())
        db.execute('begin')
        db.execute('alter type public.job_detail drop attribute work_mode')
        db.execute('alter type public.job_card drop attribute work_mode')
        previous = (MIGRATIONS / '0019_publication_dates.sql').read_text()
        db.execute(previous[previous.index('create or replace function public._job_card'):])
        db.execute('alter table public.postings drop constraint postings_work_mode_provenance, '
                   'drop column work_mode_source, drop column work_mode')
        db.execute("notify pgrst, 'reload schema'")
        db.execute('commit')
        assert contract_for_connection(db) == before
