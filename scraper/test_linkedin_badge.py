"""Known r2 false positives remain advisory, through real persistence."""
import pytest
from scraper import database, recheck, liveness
from scraper.test_database import connection
from pathlib import Path
from test_support.postgres import migrated_database
from scraper.test_linkedin_guest import TOP, STATUS, URL, Response, classify

ATTACKS = [TOP + prefix + STATUS + '</section>' for prefix in
    ['<dialog/>', '<details/>', '<div hidden/>', '<div popover/>', '<template/>', '<script/>', '<textarea/>']]
ATTACKS += [TOP + '<a href="' + href + '">' + STATUS + '</a></section>' for href in
    ['/jobs/./view/9999999999', '/jobs/x/../view/9999999999', '/jobs/%2e/view/9999999999',
     r'\jobs\view\9999999999', r'https://www.linkedin.com\jobs\view\9999999999', r'//www.linkedin.com\jobs\view\9999999999']]

@pytest.fixture(scope='module')
def migrated_database_url():
    # Exercise the current production board RPC, not just an equivalent predicate.
    with migrated_database(Path(__file__).parents[1] / 'supabase/migrations', through=26) as url:
        yield url

@pytest.mark.parametrize('body', ATTACKS)
def test_known_r2_false_positive_is_badge_never_hide(connection, monkeypatch, body):
    result = classify(body, URL)
    assert result['alive'] is None
    signal = result['linkedin_closed_signal']
    assert signal == {'phrase': 'no longer accepting applications', 'checked_at': result['liveness_checked_at'], 'url': URL}
    pid = database.persist_postings(connection, [{'source': 'linkedin', 'id': '1234567890',
        'title': 'Engineer', 'company': 'Synthetic', 'url': URL, **result}], '2026-10-07T13:00:00Z')[0]
    state = connection.execute('select liveness from postings where id=%s', (pid,)).fetchone()[0]
    assert state['linkedin_closed_signal'] == signal and 'alive' not in state
    monkeypatch.setattr(recheck.time, 'sleep', lambda _: None)
    monkeypatch.setattr(recheck, 'pinned_open', lambda r, **_: Response(r.full_url, body))
    assert recheck.recheck(connection, scope='linkedin')['closed'] == 0
    before = connection.execute('select liveness from postings where id=%s', (pid,)).fetchone()[0]
    recheck.recheck(connection, scope='linkedin', checker=lambda _: {'alive': None, 'liveness_reason': 'http-429-uncertain'})
    after = connection.execute('select liveness from postings where id=%s', (pid,)).fetchone()[0]
    assert after['linkedin_closed_signal'] == before['linkedin_closed_signal'] and 'alive' not in after
    for view in ['all', 'new-for-me']:
        assert connection.execute("select id::text from board_postings(filter => %s, availability => 'active')", (view,)).fetchall() == [(pid,)]
    connection.execute("update posting_status set status='seen' where posting_id=%s", (pid,))
    assert connection.execute("select id::text from board_postings(filter => 'seen', availability => 'active')").fetchall() == [(pid,)]
    assert connection.execute("select id::text from board_postings(availability => 'inactive')").fetchall() == []


def test_advisory_upserts_preserve_alive_state_and_newer_signal(connection):
    row = {'source': 'linkedin', 'id': '1234567890', 'title': 'Engineer', 'company': 'Synthetic', 'url': URL}
    newer = {'phrase': 'no longer accepting applications', 'checked_at': '2026-10-07T14:00:00Z', 'url': URL}
    pid = database.persist_postings(connection, [{**row, 'linkedin_closed_signal': newer}], newer['checked_at'])[0]
    connection.execute("update postings set liveness = liveness || '{\"alive\":true}'::jsonb where id=%s", (pid,))
    older = {**newer, 'checked_at': '2026-10-07T13:00:00Z'}
    database.persist_postings(connection, [{**row, 'linkedin_closed_signal': older, 'alive': False}], newer['checked_at'])
    database.persist_postings(connection, [row], newer['checked_at'])
    state = connection.execute('select liveness from postings where id=%s', (pid,)).fetchone()[0]
    assert state['alive'] is True and state['linkedin_closed_signal'] == newer


def test_closed_open_unknown_closed_transitions(connection, monkeypatch):
    ticks = iter(['2026-10-07T14:00:00Z', '2026-10-07T14:01:00Z',
                  '2026-10-07T14:02:00Z', '2026-10-07T14:03:00Z'])
    monkeypatch.setattr(liveness, '_checked_at', lambda: next(ticks))
    url = 'https://www.linkedin.com/jobs/view/4462954347'
    row = {'source': 'linkedin', 'id': '4462954347', 'title': 'Engineer',
           'company': 'Synthetic', 'url': url}
    pid = database.persist_postings(connection, [row], '2026-10-07T13:00:00Z')[0]
    monkeypatch.setattr(recheck.time, 'sleep', lambda _: None)
    body = TOP + STATUS + '</section>'
    monkeypatch.setattr(recheck, 'pinned_open', lambda r, **_: Response(r.full_url, body))
    def state():
        return connection.execute('select liveness from postings where id=%s', (pid,)).fetchone()[0]
    recheck.recheck(connection, scope='linkedin')
    original = state()['linkedin_closed_signal']
    body = TOP + '</section>'  # A bare 200 is UNKNOWN, not open.
    recheck.recheck(connection, scope='linkedin')
    assert state()['linkedin_closed_signal'] == original
    body = (Path(__file__).parent / 'fixtures/linkedin-guest/4462954347-2026-10-07.html').read_text()
    recheck.recheck(connection, scope='linkedin')
    assert state()['linkedin_closed_signal'] is None
    cleared_at = state()['linkedin_closed_signal_cleared_at']
    assert cleared_at > original['checked_at']
    assert 'alive' not in state()
    # No-evidence harvest and failed rechecks must preserve the clear receipt.
    database.persist_postings(connection, [row], '2026-10-07T14:00:00Z')
    recheck.recheck(connection, scope='linkedin', checker=lambda _: {'liveness_reason': 'http-429-uncertain'})
    assert state()['linkedin_closed_signal'] is None
    assert state()['linkedin_closed_signal_cleared_at'] == cleared_at
    # A stale harvest closure cannot resurrect the badge after a newer clear.
    database.persist_postings(connection, [{**row, 'linkedin_closed_signal': original}], '2026-10-07T14:00:00Z')
    assert state()['linkedin_closed_signal'] is None
    body = TOP + STATUS + '</section>'
    recheck.recheck(connection, scope='linkedin')
    assert state()['linkedin_closed_signal']['checked_at'] > original['checked_at']
    assert 'alive' not in state()
    assert connection.execute("select id::text from board_postings(availability => 'active')").fetchall() == [(pid,)]


@pytest.mark.parametrize('job_id', ['4462954347', '4461128829'])
def test_captured_open_harvest_clears_only_with_validated_evidence(connection, job_id, tmp_path):
    url = f'https://www.linkedin.com/jobs/view/{job_id}'
    row = {'source': 'linkedin', 'id': job_id, 'title': 'Engineer', 'company': 'Synthetic', 'url': url}
    closed = classify(TOP + STATUS + '</section>', url)
    pid = database.persist_postings(connection, [{**row, **closed}], '2026-10-07T13:00:00Z')[0]
    body = (Path(__file__).parent / f'fixtures/linkedin-guest/{job_id}-2026-10-07.html').read_text()
    opened = classify(body, url)
    assert opened['liveness_reason'] == 'linkedin-open-signal'
    assert opened['alive'] is None
    from scraper.test_harvest import load_harvest_module
    import json
    harvest = load_harvest_module()
    harvest_row = {field: harvest.OUTPUT_DEFAULTS.get(field) for field in harvest.OUTPUT_FIELDS}
    checked = harvest.apply_liveness_checks([{**harvest_row, **row}], lambda _: opened)
    output = harvest.append_postings(tmp_path, '2026-10-07', checked)
    serialized = json.loads(output.read_text())
    assert serialized['linkedin_closed_signal_cleared_at'] == opened['liveness_checked_at']
    database.persist_postings(connection, [serialized], '2026-10-07T14:00:00Z')
    state = connection.execute('select liveness from postings where id=%s', (pid,)).fetchone()[0]
    assert state['linkedin_closed_signal'] is None
    assert state['linkedin_closed_signal_cleared_at'] == opened['liveness_checked_at']
    assert 'alive' not in state


OPEN_TITLE = '<h2 class="top-card-layout__title">Synthetic Engineer</h2>'

@pytest.mark.parametrize('body,status,final', [
    (TOP + '</section>', 200, None),
    (TOP + '<h2 class="top-card-layout__title"></h2></section>', 200, None),
    (TOP + '<div hidden>' + OPEN_TITLE + '</div></section>', 200, None),
    (TOP + '<template>' + OPEN_TITLE + '</template></section>', 200, None),
    (TOP + OPEN_TITLE, 200, None),
    (TOP + OPEN_TITLE + '</section><!-- unfinished', 200, None),
    (TOP + OPEN_TITLE + '<figure class="closed-job"></figure></section>', 200, None),
    (TOP + OPEN_TITLE + STATUS.replace('No longer accepting applications', 'Unsupported') + '</section>', 200, None),
    (TOP + OPEN_TITLE + '<a href="/jobs/view/9999999999">Other</a></section>', 200, None),
    (TOP + OPEN_TITLE + '</section><form>Sign in</form>', 200, None),
    (TOP + OPEN_TITLE + '</section>', 429, None),
    (TOP + OPEN_TITLE + '</section>', 200, 'https://www.linkedin.com/authwall'),
])
def test_uncertain_open_shapes_keep_closed_badge(connection, monkeypatch, body, status, final):
    signal = {'phrase': 'no longer accepting applications', 'checked_at': '2026-10-07T13:00:00Z', 'url': URL}
    row = {'source': 'linkedin', 'id': '1234567890', 'title': 'Engineer', 'company': 'Synthetic', 'url': URL}
    pid = database.persist_postings(connection, [{**row, 'linkedin_closed_signal': signal}], signal['checked_at'])[0]
    monkeypatch.setattr(recheck.time, 'sleep', lambda _: None)
    monkeypatch.setattr(recheck, 'pinned_open', lambda r, **_: Response(final or r.full_url, body, status))
    recheck.recheck(connection, scope='linkedin')
    state = connection.execute('select liveness from postings where id=%s', (pid,)).fetchone()[0]
    assert state['linkedin_closed_signal'] == signal
    assert 'linkedin_closed_signal_cleared_at' not in state
    assert 'alive' not in state


def test_fetch_failure_and_unvalidated_null_harvest_keep_badge(connection, monkeypatch):
    signal = {'phrase': 'no longer accepting applications', 'checked_at': '2026-10-07T13:00:00Z', 'url': URL}
    row = {'source': 'linkedin', 'id': '1234567890', 'title': 'Engineer', 'company': 'Synthetic', 'url': URL}
    pid = database.persist_postings(connection, [{**row, 'linkedin_closed_signal': signal}], signal['checked_at'])[0]
    database.persist_postings(connection, [{**row, 'linkedin_closed_signal': None,
        'linkedin_closed_signal_cleared_at': '2026-10-07T14:00:00Z'}], '2026-10-07T14:00:00Z')
    def offline(_):
        raise OSError('synthetic offline')
    recheck.recheck(connection, scope='linkedin', checker=offline)
    state = connection.execute('select liveness from postings where id=%s', (pid,)).fetchone()[0]
    assert state['linkedin_closed_signal'] == signal
    assert 'linkedin_closed_signal_cleared_at' not in state
