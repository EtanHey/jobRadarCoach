from scripts.backfill_work_mode import candidates, backfill


def test_plan_is_conservative_and_dry_run_does_not_write():
    rows = [dict(id='a', source='linkedin', location='Israel (Hybrid)', remote=None),
            dict(id='b', source='lever', location='Israel (Remote)', remote=False),
            dict(id='c', source='test', location='Israel', remote=None),
            dict(id='d', source='test', location='Israel (Remote)', remote=None, work_mode='hybrid')]
    assert [(row['id'], mode) for row, mode in candidates(rows)] == [('a', 'hybrid')]
    class Connection:
        def execute(self, *_):
            raise AssertionError('dry-run attempted a write')
    assert backfill(Connection(), rows, apply=False)['applied'] == 0


def test_apply_counts_only_guarded_updated_rows():
    class Result:
        rowcount = 0
    class Connection:
        def execute(self, query, params):
            assert 'remote is null' in query and 'work_mode is null' in query
            assert 'location is not distinct from' in query
            assert params[-1] == 'Israel (Remote)'
            return Result()
    result = backfill(Connection(), [dict(id='a', source='test', location='Israel (Remote)', remote=None)], apply=True)
    assert result['applied'] == 0 and result['skipped_race'] == 1


def test_real_backfill_is_idempotent_and_preserves_explicit_modes():
    from pathlib import Path
    import psycopg
    from psycopg.rows import dict_row
    from test_support.postgres import migrated_database
    with migrated_database(Path(__file__).parents[1] / 'supabase/migrations', through=19) as url:
        with psycopg.connect(url, row_factory=dict_row) as connection:
            connection.execute("insert into postings(source,external_id,url,title,company,location) values ('fixture','one','https://example.test','Engineer','Example','Israel (Hybrid)')")
            rows = connection.execute('select * from postings').fetchall()
            assert backfill(connection, rows)['planned'] == 1
            assert connection.execute('select work_mode from postings').fetchone()['work_mode'] is None
            assert backfill(connection, rows, apply=True)['applied'] == 1
            assert connection.execute('select work_mode,remote from postings').fetchone() == {'work_mode':'hybrid','remote':None}
            assert backfill(connection, rows, apply=True)['skipped_race'] == 1
            assert backfill(connection, connection.execute('select * from postings').fetchall(), apply=True)['planned'] == 0
