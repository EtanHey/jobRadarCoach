"""Known r2 false positives remain advisory, through real persistence."""
import pytest
from scraper import database, recheck
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
