"""Real SQL selection tests over synthetic postings in a disposable database."""
from pathlib import Path
import json
from uuid import uuid4

import pytest

psycopg = pytest.importorskip('psycopg')
from test_support.postgres import DatabaseUnavailable, migrated_database
from classifier.persistence import list_scoring_candidates
from classifier.test_core import profile_snapshot
from extractor.job import select_postings


@pytest.fixture(scope='module')
def database_url():
    try:
        with migrated_database(Path(__file__).parents[1] / 'supabase/migrations', through=27) as url:
            yield url
    except DatabaseUnavailable as error:
        pytest.skip(str(error))


@pytest.fixture
def connection(database_url):
    with psycopg.connect(database_url) as connection:
        connection.execute("delete from public.profile")
        for field, value in profile_snapshot().items():
            if field not in {"people", "connectors"}:
                connection.execute("insert into public.profile(field,value) values(%s,%s::jsonb)", (field,json.dumps(value)))
        yield connection
        connection.rollback()


def seed(connection, alive):
    posting_id = str(uuid4())
    connection.execute(
        "insert into public.postings(id,source,external_id,url,title,company,raw_jd,liveness) "
        "values(%s,'synthetic',%s,'https://example.test/job','Engineer','Example',"
        "repeat('Substantive synthetic engineering description. ',5),%s::jsonb)",
        (posting_id, posting_id, json.dumps(alive)),
    )
    connection.execute('insert into public.posting_status(posting_id) values(%s)', (posting_id,))
    return posting_id


@pytest.mark.parametrize('stage', ['score', 'extract'])
@pytest.mark.parametrize('mode', ['batch', 'assigned', 'claimable'])
def test_closed_is_skipped_before_limit_and_unknown_remains_eligible(connection, stage, mode):
    closed = seed(connection, {'alive': False})
    active = [seed(connection, value) for value in (
        {'alive': True}, {}, {'alive': None}, {'alive': 'false'},
    )]
    options = {'limit': 10}
    if mode == 'assigned':
        options['posting_ids'] = [closed, *active]
    if mode == 'claimable':
        options['claimable_stage'] = stage
    def selected(limit):
        options['limit'] = limit
        if stage == 'score':
            return list_scoring_candidates(connection, **options)
        return [row['id'] for row in select_postings(connection, **options)]
    assert set(selected(10)) == set(active)
    # A limit cannot let a closed row starve a valid row in either sort order.
    connection.execute("update public.postings set first_seen_at=now()-interval '1 day' where id=%s", (closed,))
    connection.execute('update public.postings set posted_at=now() where id=%s', (closed,))
    assert len(selected(1)) == 1
    assert selected(1)[0] in active
