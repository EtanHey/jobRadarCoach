"""Runs in python-db CI against migrated disposable PostgreSQL, never hosted data."""

import json
import os
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from psycopg.rows import dict_row

from classifier.persistence import _labels
from scraper.test_annotate import structured_annotation
from scripts import eligibility_backfill as backfill
from scripts.test_eligibility_backfill import profile_inputs
from test_support.postgres import DatabaseUnavailable, migrated_database


def test_real_batches_preserve_scores_and_are_idempotent():
    if not os.environ.get('DATABASE_URL'):
        if os.environ.get('JOBRADAR_REQUIRE_PG17') == '1':
            pytest.fail('CI requires DATABASE_URL')
        pytest.skip('No explicit disposable DATABASE_URL; no local Docker probe')
    try:
        with migrated_database(Path(__file__).parents[1] / 'supabase/migrations', through=37) as url:
            with psycopg.connect(url, autocommit=True, row_factory=dict_row) as connection:
                snapshot, _, fingerprint = profile_inputs()
                connection.execute('delete from profile')
                for field, value in snapshot.items():
                    if field in {'people', 'connectors'}:
                        continue
                    connection.execute('insert into profile(field,value) values (%s,%s::jsonb)',
                                       (field, json.dumps(value)))
                ids = []
                for index, location in enumerate(['Tel Aviv', 'Remote - United States', 'Remote', 'Remote', 'Tel Aviv', None]):
                    posting_id = uuid4()
                    ids.append(posting_id)
                    connection.execute(
                        "insert into postings(id,source,external_id,url,title,company,location,raw_jd) "
                        "values (%s,'fixture',%s,'https://example.test','Engineer','Example',%s,%s)",
                        (posting_id, str(posting_id), location, 'Build React products. ' * 30))
                    payload = structured_annotation(str(posting_id))
                    payload['luna_status'] = 'ok'
                    if index == 5:
                        facts = {field: dict(value=None, evidence_quote=None)
                                 for field in ('location', 'remote', 'seniority', 'salary')}
                        facts.update(stack=[], location=dict(value='Israel', evidence_quote='Remote from Israel'))
                        connection.execute('update postings set raw_jd=%s where id=%s',
                                           ('Remote from Israel. ' * 30, posting_id))
                        connection.execute(
                            "insert into posting_extractions(posting_id,brain,model,extractor_version,"
                            "schema_sha256,jd_sha256,fingerprint,facts) "
                            "values (%s,'fixture','fixture','fixture',%s,%s,%s,%s::jsonb)",
                            (posting_id, 'a'*64, 'b'*64, 'c'*64, json.dumps(facts)))
                    if index == 3:
                        payload.update(eligibility='eligible', eligibility_reason='Existing decision')
                    connection.execute(
                        "insert into posting_scores(posting_id,score,reasons,labels,brain,model,scorer_version,"
                        "posting_sha256,profile_sha256,history_sha256,score_payload) "
                        "values (%s,%s,%s::jsonb,%s::jsonb,'fixture','fixture','1.1',%s,%s,%s,%s::jsonb)",
                        (posting_id, payload['fit_score'], json.dumps(payload['reasons']),
                         json.dumps(_labels(payload)), 'a'*64, fingerprint if index != 4 else 'b'*64,
                         'c'*64, json.dumps(payload)))

                def state():
                    return {row['posting_id']: row for row in connection.execute('select * from posting_scores')}

                before = state()
                preview = backfill.backfill_connection(connection, batch_size=2)
                assert preview['counts'] == dict(eligible=2, blocked=1, unknown=1)
                assert preview['applied'] == 0 and state() == before
                receipt = backfill.backfill_connection(connection, apply=True, batch_size=2)
                assert receipt['applied'] == 4 and receipt['batches'] == 2
                after = state()
                for posting_id in [*ids[:3], ids[5]]:
                    old, new = before[posting_id].copy(), after[posting_id].copy()
                    old_payload, new_payload = old.pop('score_payload'), new.pop('score_payload')
                    assert old == new  # Includes all hashes, score, reasons, labels and timestamp.
                    assert {k: v for k, v in new_payload.items() if not k.startswith('eligibility')} == old_payload
                    assert new_payload['eligibility'] in {'eligible', 'blocked', 'unknown'}
                    assert new_payload['eligibility_reason'].strip()
                assert after[ids[5]]['score_payload']['eligibility'] == 'eligible'
                for posting_id in ids[3:5]:
                    assert before[posting_id] == after[posting_id]
                assert backfill.backfill_connection(connection, apply=True)['applied'] == 0
                # A stale plan cannot replace an eligibility written since planning.
                assert backfill.apply_rows(connection, [(dict(id=ids[0]), {
                    'eligibility': 'blocked', 'eligibility_reason': 'Must never overwrite'})], fingerprint) == 0
                assert state() == after
    except DatabaseUnavailable:
        if os.environ.get('JOBRADAR_REQUIRE_PG17') == '1':
            pytest.fail('Required disposable PostgreSQL unavailable')
        pytest.skip('Disposable PostgreSQL unavailable')


def test_recompute_unknown_real_sql_guards_and_idempotency():
    if not os.environ.get('DATABASE_URL'):
        if os.environ.get('JOBRADAR_REQUIRE_PG17') == '1':
            pytest.fail('CI requires DATABASE_URL')
        pytest.skip('No explicit disposable DATABASE_URL; no local Docker probe')
    try:
        with migrated_database(Path(__file__).parents[1] / 'supabase/migrations', through=37) as url:
            with psycopg.connect(url, autocommit=True, row_factory=dict_row) as connection:
                snapshot, _, fingerprint = profile_inputs()
                connection.execute('delete from profile')
                for field, value in snapshot.items():
                    if field not in {'people', 'connectors'}:
                        connection.execute('insert into profile(field,value) values (%s,%s::jsonb)', (field, json.dumps(value)))
                for value, location, profile in [
                    ('unknown', 'Tel Aviv', fingerprint), ('unknown', 'Remote', fingerprint),
                    ('eligible', 'Remote', fingerprint), ('blocked', 'Tel Aviv', fingerprint),
                    ('unknown', 'Tel Aviv', 'b'*64), (None, 'Tel Aviv', fingerprint),
                ]:
                    posting_id = uuid4()
                    connection.execute(
                        "insert into postings(id,source,external_id,url,title,company,location,raw_jd) "
                        "values (%s,'fixture',%s,'https://example.test','Engineer','Example',%s,'Israeli work permit required')",
                        (posting_id, str(posting_id), location))
                    payload = structured_annotation(str(posting_id))
                    payload['luna_status'] = 'ok'
                    if value is not None:
                        payload.update(eligibility=value, eligibility_reason='old')
                    connection.execute(
                        "insert into posting_scores(posting_id,score,reasons,labels,brain,model,scorer_version,"
                        "posting_sha256,profile_sha256,history_sha256,score_payload) "
                        "values (%s,%s,%s::jsonb,%s::jsonb,'fixture','fixture','1.1',%s,%s,%s,%s::jsonb)",
                        (posting_id, payload['fit_score'], json.dumps(payload['reasons']),
                         json.dumps(_labels(payload)), 'a'*64, profile, 'c'*64, json.dumps(payload)))

                def state():
                    return {r['posting_id']: r for r in connection.execute('select * from posting_scores')}

                before = state()
                preview = backfill.backfill_connection(connection, recompute_unknown=True, batch_size=1)
                assert preview['planned'] == 2 and preview['applied'] == 0 and state() == before
                receipt = backfill.backfill_connection(connection, apply=True, recompute_unknown=True, batch_size=1)
                assert receipt['applied'] == 2
                after = state()
                for key, old in before.items():
                    new = after[key]
                    if old['profile_sha256'] != fingerprint or old['score_payload'].get('eligibility') != 'unknown':
                        assert new == old
                    else:
                        assert {k: v for k, v in new.items() if k != 'score_payload'} == {k: v for k, v in old.items() if k != 'score_payload'}
                        strip = lambda payload: {k: v for k, v in payload.items() if k not in {'eligibility', 'eligibility_reason'}}
                        assert strip(new['score_payload']) == strip(old['score_payload'])
                assert backfill.backfill_connection(connection, apply=True, recompute_unknown=True)['applied'] == 0
                assert state() == after
                key = next(k for k, r in after.items() if r['score_payload'].get('eligibility') == 'blocked')
                assert backfill.apply_rows(connection, [(dict(id=key), {'eligibility': 'eligible', 'eligibility_reason': 'stale'})], fingerprint, recompute_unknown=True) == 0
                assert state() == after
    except DatabaseUnavailable:
        if os.environ.get('JOBRADAR_REQUIRE_PG17') == '1':
            pytest.fail('Required disposable PostgreSQL unavailable')
        pytest.skip('Disposable PostgreSQL unavailable')
