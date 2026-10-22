"""Synthetic scorer parity and offline backfill contracts; no model or DB needed."""

from contextlib import nullcontext
from copy import deepcopy
from uuid import UUID

import pytest

from classifier import core, persistence, projection
from classifier.test_core import posting, profile_snapshot, wire_annotation
from scraper.brain import BrainResult
from scripts import eligibility_backfill as backfill


def profile_inputs():
    snapshot = profile_snapshot()
    snapshot['candidate.location'] = 'Central Israel'
    snapshot['candidate.open_to.geographies'] = ['Central Israel', 'Remote']
    profile = projection.profile_contract(snapshot)
    return snapshot, profile, persistence._sha256(profile)


def score_row(**changes):
    _, _, profile_sha256 = profile_inputs()
    return dict(posting(), profile_sha256=profile_sha256, score_payload={'fit_score': 72}, **changes)


@pytest.mark.parametrize('location,remote,work_mode,jd,extraction', [
    ('Tel Aviv', None, None, '', None),
    ('Remote', True, 'remote', 'Applicants must reside in the United States.', None),
    ('Remote', True, 'remote', 'Build React products.', None),
    ('Haifa', False, 'hybrid', '', None),
    ('Haifa', True, 'remote', '', None),
    ('Tel Aviv', True, 'hybrid', 'Flexible hybrid work model', None),
    ('Tel Aviv', None, None,
     'Applicants must have the legal right to work in the country where the position is based, '
     'without the need for visa sponsorship', None),
    (None, None, None, 'Remote from Israel', {'facts': {
        'location': {'value': 'Israel', 'evidence_quote': 'Remote from Israel'}}}),
])
def test_matches_fresh_scorer(location, remote, work_mode, jd, extraction):
    snapshot, profile, profile_sha256 = profile_inputs()
    row = score_row()
    row.update(location=location, remote=remote, work_mode=work_mode,
               raw_jd=(jd + '\n' + row['raw_jd']), posting_extractions=extraction)
    original = deepcopy(row)
    result = core.score_posting(snapshot, row, [], brain_runner=lambda request, _: BrainResult(
        wire_annotation(row['id']), 'codex', 'fixture-model', request=request))
    assert result is not None
    planned = list(backfill.plan_rows([row], profile, profile_sha256))
    decision = planned[0][1]
    assert decision == {key: result.annotation[key] for key in ('eligibility', 'eligibility_reason')}
    assert set(decision) == {'eligibility', 'eligibility_reason'}
    assert decision['eligibility'] in {'eligible', 'blocked', 'unknown'}
    assert isinstance(decision['eligibility_reason'], str) and decision['eligibility_reason'].strip()
    assert row == original


def test_plan_is_current_profile_only_and_never_overwrites_even_null():
    _, profile, fingerprint = profile_inputs()
    rows = [score_row() for _ in range(5)]
    for row, value in zip(rows[1:4], ['blocked', 'unknown', None]):
        row['score_payload']['eligibility'] = value
    rows[4]['profile_sha256'] = '0' * 64
    assert [row for row, _ in backfill.plan_rows(rows, profile, fingerprint)] == rows[:1]
    row, decision = list(backfill.plan_rows(rows, profile, fingerprint))[0]
    row['score_payload'].update(decision)
    assert list(backfill.plan_rows(rows, profile, fingerprint)) == []


def test_apply_counts_guarded_writes_and_sends_only_two_keys():
    _, profile, fingerprint = profile_inputs()
    planned = list(backfill.plan_rows([score_row(), score_row()], profile, fingerprint))

    class Connection:
        calls = 0

        def execute(self, query, params):
            assert query == backfill.UPDATE
            assert "not (score_payload ? 'eligibility')" in query
            assert 'profile_sha256 = %s' in query
            assert set(params[0].obj) == {'eligibility', 'eligibility_reason'}
            self.calls += 1
            self.rowcount = int(self.calls == 1)  # Second row got eligibility concurrently.
            return self

    assert backfill.apply_rows(Connection(), planned, fingerprint) == 1


def test_dry_run_batches_counts_and_sample_limit_without_writes():
    snapshot, _, _ = profile_inputs()
    rows = [score_row() for _ in range(24)]
    for index, row in enumerate(rows, 1):
        row.update(id=UUID(int=index), location=['Tel Aviv', 'Remote', 'Remote - United States'][index % 3])

    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def execute(self, query, params=None):
            if 'from public.profile' in query:
                self.rows = [dict(field=k, value=v) for k, v in snapshot.items()]
            else:
                assert 'for update' not in query
                self.rows = [row for row in rows if row['id'] > params[1]][:params[2]]
            return self

        def fetchall(self):
            return self.rows

    class Connection:
        transaction = staticmethod(nullcontext)
        cursor = staticmethod(lambda **_: Cursor())

        def execute(self, query):
            assert query == 'set transaction isolation level repeatable read read only'

    result = backfill.backfill_connection(Connection(), batch_size=5)
    assert result['counts'] == dict(eligible=8, blocked=8, unknown=8)
    assert result['batches'] == 5 and result['planned'] == 24 and result['applied'] == 0
    assert len(result['samples']) == 20
    assert set(result['samples'][0]) == {'id', 'company', 'location', 'decision', 'reason'}


@pytest.mark.parametrize('batch_size', [0, 1001, True])
def test_invalid_batch_size(batch_size):
    with pytest.raises(ValueError, match='batch_size'):
        backfill.backfill_connection(None, batch_size=batch_size)


@pytest.mark.parametrize('flags,expected', [([], False), (['--dry-run'], False), (['--apply'], True)])
def test_cli_mode_and_sanitized_errors(monkeypatch, capsys, flags, expected):
    secret = 'postgresql://private:secret@synthetic.invalid/jobs'
    monkeypatch.setenv('DATABASE_URL', secret)
    monkeypatch.setattr(backfill.psycopg, 'connect', lambda *a, **k: nullcontext(None))

    def run(connection, *, apply, batch_size):
        assert apply is expected
        raise psycopg_error(secret)

    psycopg_error = backfill.psycopg.OperationalError
    monkeypatch.setattr(backfill, 'backfill_connection', run)
    assert backfill.main(flags) == 1
    output = capsys.readouterr()
    assert not output.out and secret not in output.err and 'secret' not in output.err


def test_recompute_selects_only_unknown_current_profile_and_preserves_payload():
    _, profile, fingerprint = profile_inputs()
    rows = []
    for value in ['unknown', 'eligible', 'blocked', None, 'unexpected']:
        row = score_row()
        row.update(location='Tel Aviv', raw_jd='Israeli work permit required')
        row['score_payload'].update(eligibility=value, eligibility_reason='old', custom={'keep': True})
        rows.append(row)
    missing, stale = score_row(), deepcopy(rows[0])
    stale['profile_sha256'] = '0' * 64
    rows += [missing, stale]
    original = deepcopy(rows)
    planned = list(backfill.plan_rows(rows, profile, fingerprint, recompute_unknown=True))
    assert len(planned) == 1 and planned[0][0] is rows[0]
    assert planned[0][1]['eligibility'] == 'eligible'
    assert rows == original
    rows[0]['score_payload'].update(planned[0][1])
    assert list(backfill.plan_rows(rows, profile, fingerprint, recompute_unknown=True)) == []
    assert rows[0]['score_payload']['custom'] == {'keep': True}
    assert rows[1:] == original[1:]


def test_recompute_update_guards_current_unknown_and_skips_identical_decisions():
    _, profile, fingerprint = profile_inputs()
    row = score_row()
    row.update(location='Remote', raw_jd='Build products')
    row['score_payload'].update(eligibility='unknown', eligibility_reason='old')
    planned = list(backfill.plan_rows([row], profile, fingerprint, recompute_unknown=True))

    class Connection:
        def execute(self, query, params):
            assert query == backfill.RECOMPUTE_UPDATE
            assert "score_payload->>'eligibility' = 'unknown'" in query
            assert 'profile_sha256 = %s' in query and 'is distinct from' in query
            patch, posting_id, profile_id, value, reason = params
            assert profile_id == fingerprint and posting_id == row['id']
            assert set(patch.obj) == {'eligibility', 'eligibility_reason'}
            assert (value.obj, reason.obj) == (patch.obj['eligibility'], patch.obj['eligibility_reason'])
            payload = row['score_payload']
            self.rowcount = int(payload['eligibility'] == 'unknown' and any(payload[k] != v for k, v in patch.obj.items()))
            if self.rowcount:
                payload.update(patch.obj)
            return self

    connection = Connection()
    assert backfill.apply_rows(connection, planned, fingerprint, recompute_unknown=True) == 1
    assert backfill.apply_rows(connection, planned, fingerprint, recompute_unknown=True) == 0
    assert list(backfill.plan_rows([row], profile, fingerprint, recompute_unknown=True)) == []
    row['score_payload']['eligibility'] = 'blocked'
    assert backfill.apply_rows(connection, planned, fingerprint, recompute_unknown=True) == 0


def test_recompute_cli_is_dry_run_by_default(monkeypatch, capsys):
    monkeypatch.setenv('DATABASE_URL', 'postgresql://synthetic.invalid/jobs')
    monkeypatch.setattr(backfill.psycopg, 'connect', lambda *a, **k: nullcontext(None))

    def run(connection, *, apply, batch_size, recompute_unknown):
        assert not apply and recompute_unknown and batch_size == 100
        return {'dry_run': True, 'applied': 0}

    monkeypatch.setattr(backfill, 'backfill_connection', run)
    assert backfill.main(['--recompute-unknown']) == 0
    assert '"applied": 0' in capsys.readouterr().out
