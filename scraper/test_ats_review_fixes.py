"""Round-one regressions: synthetic streamed boards and persisted clocked state."""
import io
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import scraper.ats_liveness as module


@pytest.fixture
def clock(monkeypatch):
    class Clock(datetime):
        current = datetime(2026, 10, 5, tzinfo=timezone.utc)

        @classmethod
        def now(cls, tz=None):
            return cls.current

    monkeypatch.setattr(module, 'datetime', Clock)
    return Clock


def observe(clock, state, minutes, direct, alive=False):
    clock.current = datetime(2026, 10, 5, tzinfo=timezone.utc) + timedelta(minutes=minutes)
    result = {'alive': alive, 'liveness_checked_at': clock.current.isoformat(),
              'liveness_reason': 'ats-active-list-absent' if alive is False else 'board-unknown:OSError'}
    update = module.reliability_update({'liveness': state}, result, direct)
    state.update(update)
    return update


@pytest.mark.parametrize('host', ['api.lever.co', 'api.eu.lever.co'])
def test_large_complete_lever_board_is_streamed_once_and_not_unknown(monkeypatch, host):
    body = json.dumps([{'id': 'kept', 'description': 'x' * 2_100_000}]).encode()
    reads, opens = [], []

    class Response(io.BytesIO):
        def read(self, size=-1):
            reads.append(size)
            return super().read(size)

    monkeypatch.setattr(module, 'pinned_open', lambda request, **_: opens.append(request.full_url) or Response(body))
    board = module.BoardChecker()
    url = 'https://jobs.eu.lever.co/acme/kept' if '.eu.' in host else 'https://jobs.lever.co/acme/kept'
    row = {'source': 'lever', 'external_id': 'lever:acme:kept', 'url': url}
    assert board(row)['alive'] is True
    assert board(dict(row, external_id='lever:acme:missing'))['alive'] is False
    assert len(opens) == 1 and opens[0].startswith(f'https://{host}/')
    assert len(reads) > 1 and max(reads) <= 65_536


@pytest.mark.parametrize('host,cap', [('api.lever.co', 16_000_000), ('boards-api.greenhouse.io', 2_000_000)])
def test_transport_stops_at_source_cap_plus_one(monkeypatch, host, cap):
    consumed = []

    class Response(io.BytesIO):
        def read(self, size=-1):
            chunk = super().read(size)
            consumed.append(len(chunk))
            return chunk

    monkeypatch.setattr(module, 'pinned_open', lambda *_a, **_k: Response(b' ' * (cap + 1000)))
    with pytest.raises(ValueError, match='response cap'):
        module.public_get()(f'https://{host}/synthetic')
    assert sum(consumed) == cap + 1


def test_distinct_misses_minutes_apart_cannot_close_or_poll(clock):
    state, calls = {}, []
    direct = lambda _: calls.append(True) or {'alive': False, 'liveness_status': 404}
    for minute in [0, 2, 15, 44]:
        update = observe(clock, state, minute, direct)
        assert update['ats_miss_count'] == 1 and update['last_attempt_verdict'] == 'pending'
        assert state.get('alive') is not False and calls == []
    assert observe(clock, state, 45, direct)['alive'] is False
    assert len(calls) == 1


@pytest.mark.parametrize('first', [None, 'invalid', '2026-10-06T00:00:00+00:00'])
def test_unusable_legacy_strike_time_starts_a_safe_spacing_window(clock, first):
    state = {'ats_miss_count': 1, 'ats_last_list_checked_at': first}
    update = observe(clock, state, 0, lambda _: pytest.fail('no trustworthy elapsed window'))
    assert update['ats_miss_count'] == 1 and update['last_attempt_verdict'] == 'pending'


def test_delayed_row_processing_does_not_age_a_too_early_board_snapshot(clock):
    state = {}
    observe(clock, state, 0, lambda _: None)
    clock.current += timedelta(minutes=60)
    early = {'alive': False, 'liveness_checked_at': '2026-10-05T00:02:00+00:00'}
    update = module.reliability_update({'liveness': state}, early,
                                     lambda _: pytest.fail('snapshot was fetched only two minutes later'))
    assert update['ats_miss_count'] == 1 and update['last_attempt_verdict'] == 'pending'


def test_repeated_url_uncertainty_quiets_alerts_and_backs_off_after_three(clock):
    state, calls = {}, []
    direct = lambda _: calls.append(clock.current) or {'alive': None, 'liveness_reason': 'posting-url-unknown'}
    observe(clock, state, 0, direct)
    for minute in [60, 120, 180]:
        observe(clock, state, minute, direct)
    assert len(calls) == 3 and state['ats_alert_count'] == 1
    for minute in [240, 600, 1560, 1619]:
        observe(clock, state, minute, direct)
    assert len(calls) == 3 and state['ats_alert_count'] == 1
    observe(clock, state, 1620, direct)
    assert len(calls) == 4 and state['ats_alert_count'] == 1


def test_direct_checks_stop_for_twenty_four_hours_after_third_unknown(clock):
    state, calls = {}, []
    direct = lambda _: calls.append(True) or {'alive': None, 'liveness_reason': 'posting-url-unknown'}
    for minute in [0, 60, 120, 180, 240, 600, 1619]:
        observe(clock, state, minute, direct)
    assert len(calls) == 3
    observe(clock, state, 1620, direct)
    assert len(calls) == 4


def test_unknown_transitions_and_each_tenant_list_error_alert(clock):
    state = {}
    observe(clock, state, 0, lambda _: None)
    observe(clock, state, 60, lambda _: {'alive': None, 'liveness_reason': 'posting-url-unknown'})
    observe(clock, state, 120, lambda _: {'alive': None, 'liveness_reason': 'TimeoutError'})
    assert state['ats_alert_count'] == 2
    for minute in [180, 240]:
        observe(clock, state, minute, lambda _: pytest.fail('list error cannot poll'), alive=None)
    assert state['ats_alert_count'] == 4


def test_list_presence_preserves_own_url_and_resets_url_backoff(clock):
    state = {'liveness_final_url': 'https://careers.acme.example/jobs/1', 'ats_miss_count': 2,
             'ats_url_unknown_count': 3, 'ats_url_next_check_at': '2026-10-06T00:00:00+00:00'}
    result = {'alive': True, 'liveness_reason': 'ats-active-list-present',
              'liveness_final_url': 'https://boards-api.greenhouse.io/v1/boards/acme/jobs'}
    state.update(module.reliability_update({'liveness': state}, result, lambda _: pytest.fail('present')))
    assert state['liveness_final_url'] == 'https://careers.acme.example/jobs/1'
    assert state['ats_miss_count'] == state['ats_url_unknown_count'] == 0
    assert state['ats_url_next_check_at'] is None


def test_hourly_checks_have_independent_concurrency():
    workflow = (Path(__file__).parents[1] / '.github/workflows/ats-liveness.yml').read_text()
    assert 'group: ats-liveness' in workflow
