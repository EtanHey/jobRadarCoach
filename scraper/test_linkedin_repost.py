"""Synthetic guest fragments: only LinkedIn's own visible posting-age label counts."""
import pytest
from scraper import database
from scraper.test_linkedin_guest import URL, GUEST, TOP, Response, classify
from scraper.test_harvest import load_harvest_module

LABEL = '<span class="posted-time-ago__text topcard__flavor--metadata">Reposted <span>2 weeks</span> ago</span>'
PAGE = TOP + '<h2 class="top-card-layout__title">Synthetic Engineer</h2>' + LABEL + '</section>'


def test_explicit_repost_flows_through_fetch_harvest_and_database(tmp_path):
    import json
    result = classify(PAGE, URL)
    signal = result['linkedin_reposted_signal']
    assert signal == {'label': 'Reposted 2 weeks ago', 'checked_at': result['liveness_checked_at'], 'url': URL}
    assert result['alive'] is None
    harvest = load_harvest_module()
    row = {key: harvest.OUTPUT_DEFAULTS.get(key) for key in harvest.OUTPUT_FIELDS}
    row.update(source='linkedin', id='1234567890', url=URL)
    checked = harvest.apply_liveness_checks([row], lambda _: result)
    serialized = json.loads(harvest.append_postings(tmp_path, '2026-10-07', checked).read_text())
    assert serialized['linkedin_reposted_signal'] == signal
    assert database._liveness_evidence(serialized)['linkedin_reposted_signal'] == signal


@pytest.mark.parametrize('label', ['2 weeks ago', 'Posted 2 weeks ago', 'Reposted', 'Reposted yesterday', 'Reposted 2 weeks ago by someone'])
def test_no_guess_from_ordinary_or_unsupported_age(label):
    assert 'linkedin_reposted_signal' not in classify(PAGE.replace('Reposted <span>2 weeks</span> ago', label), URL)


@pytest.mark.parametrize('wrapper', ['<div hidden>{}</div>', '<template>{}</template>', '<script>{}</script>', '<aside>{}</aside>', '<div aria-hidden="true">{}</div>', '<div style="display:none">{}</div>'])
def test_hidden_label_is_not_evidence(wrapper):
    assert 'linkedin_reposted_signal' not in classify(TOP + wrapper.format(LABEL) + '</section>', URL)


@pytest.mark.parametrize('body', [PAGE[:-10], PAGE + '<!-- unfinished', PAGE.replace(LABEL, '<p>Reposted 2 weeks ago</p>'), PAGE.replace('</section>', '<a href="/jobs/view/9999999999">Other</a></section>'), PAGE.replace('</section>', LABEL + '</section>')])
def test_partial_foreign_or_ambiguous_fragment_is_not_evidence(body):
    assert 'linkedin_reposted_signal' not in classify(body, URL)


@pytest.mark.parametrize('status,final', [(429, GUEST), (200, 'https://www.linkedin.com/authwall')])
def test_redirect_or_error_never_supplies_repost(status, final):
    from scraper.liveness import check_url
    assert 'linkedin_reposted_signal' not in check_url(URL, opener=lambda *_args, **_kwargs: Response(final, PAGE, status))


def test_repost_and_closure_can_coexist():
    from scraper.test_linkedin_guest import STATUS
    result = classify(PAGE.replace('</section>', STATUS + '</section>'), URL)
    evidence = database._liveness_evidence({**result, 'source': 'linkedin', 'url': URL})
    assert evidence['linkedin_reposted_signal']['label'] == 'Reposted 2 weeks ago'
    assert evidence['linkedin_closed_signal']['phrase'] == 'no longer accepting applications'


from scraper.test_database import connection, migrated_database_url


def test_real_persistence_and_recheck_keep_seen_repost_on_unknown(connection, monkeypatch):
    from scraper import recheck
    row = {'source': 'linkedin', 'id': '1234567890', 'url': URL, 'title': 'Synthetic Engineer', 'company': 'Synthetic'}
    signal = classify(PAGE, URL)['linkedin_reposted_signal']
    pid = database.persist_postings(connection, [{**row, 'linkedin_reposted_signal': signal}], signal['checked_at'])[0]
    state = lambda: connection.execute('select liveness from postings where id=%s', (pid,)).fetchone()[0]
    assert state()['linkedin_reposted_signal'] == signal
    database.persist_postings(connection, [row], signal['checked_at'])
    older = {**signal, 'label': 'Reposted 1 month ago', 'checked_at': '2020-01-01T00:00:00Z'}
    database.persist_postings(connection, [{**row, 'linkedin_reposted_signal': older}], signal['checked_at'])
    assert state()['linkedin_reposted_signal'] == signal
    recheck.recheck(connection, scope='linkedin', checker=lambda _: {'alive': None, 'liveness_reason': 'http-429-uncertain'})
    assert state()['linkedin_reposted_signal'] == signal
    monkeypatch.setattr(recheck.time, 'sleep', lambda _: None)
    monkeypatch.setattr(recheck, 'pinned_open', lambda request, **_: Response(request.full_url, PAGE.replace('2 weeks', '3 weeks')))
    recheck.recheck(connection, scope='linkedin')
    assert state()['linkedin_reposted_signal']['label'] == 'Reposted 3 weeks ago'
    assert 'alive' not in state()
    monkeypatch.setattr(recheck, 'pinned_open', lambda request, **_: Response(request.full_url, PAGE.replace('Reposted ', '')))
    recheck.recheck(connection, scope='linkedin')
    assert state()['linkedin_reposted_signal']['label'] == 'Reposted 3 weeks ago'
