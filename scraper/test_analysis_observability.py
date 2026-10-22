"""Synthetic regressions for the P10 diagnostic contract."""
import json
import os
from pathlib import Path
import subprocess

import pytest

from scraper import brain
from scraper.test_codex_brain import install_runtime, request
from scripts import local_analysis


def successful_process(command, **_kwargs):
    Path(command[command.index('--output-last-message') + 1]).write_text(
        '{"role_family":"backend","mentions_typescript":true}')
    return subprocess.CompletedProcess(command, 0)


def runtime(monkeypatch, tmp_path, process=successful_process):
    install_runtime(monkeypatch, tmp_path, process)
    binary = tmp_path / 'codex'
    binary.write_text('synthetic binary')
    monkeypatch.setattr(brain, '_discover_codex', lambda: str(binary))
    return binary


@pytest.mark.parametrize('phase', ['version_probe', 'inference'])
def test_timeout_receipt_identifies_bounded_phase(monkeypatch, tmp_path, phase):
    def timeout(*_args, **kwargs):
        raise subprocess.TimeoutExpired('PRIVATE_COMMAND', kwargs['timeout'], stderr='PRIVATE_SECRET')
    runtime(monkeypatch, tmp_path, timeout if phase == 'inference' else successful_process)
    if phase == 'version_probe':
        monkeypatch.setattr(brain, '_verify_codex_version', timeout)
    events = []
    with brain.provider_diagnostic_scope(events.append), pytest.raises(brain.BrainTransportError):
        brain.run_brain(request(), env={'BRAIN': 'codex'}, timeout_seconds=30)
    event = events[0]
    assert event['category'] == 'timeout'
    assert event['phase'] == phase
    assert 0 < event['phase_timeout_seconds'] <= (10 if phase == 'version_probe' else 30)
    assert 0 <= event['phase_elapsed_ms'] <= event['elapsed_ms']
    assert 'PRIVATE' not in json.dumps(event)


def test_probe_once_per_cycle_and_invalidates_binary_changes(monkeypatch, tmp_path):
    binary = runtime(monkeypatch, tmp_path)
    probes = []
    monkeypatch.setattr(brain, '_verify_codex_version', lambda *_a, **_k: probes.append(True))
    with brain.codex_cycle_scope():
        for _ in range(2):
            brain.run_brain(request(), env={'BRAIN': 'codex'})
        assert len(probes) == 1
        binary.write_text('replacement synthetic binary of a different size')
        brain.run_brain(request(), env={'BRAIN': 'codex'})
        assert len(probes) == 2
        replacement = tmp_path / 'replacement'
        replacement.write_bytes(binary.read_bytes())
        stat = binary.stat()
        os.utime(replacement, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        replacement.replace(binary)
        brain.run_brain(request(), env={'BRAIN': 'codex'})
        assert len(probes) == 3
    with brain.codex_cycle_scope():
        brain.run_brain(request(), env={'BRAIN': 'codex'})
    assert len(probes) == 4


@pytest.mark.parametrize('recover', [False, True])
def test_probe_timeout_retries_once_and_caches_cycle_result(monkeypatch, tmp_path, recover):
    runtime(monkeypatch, tmp_path)
    budgets = []
    def probe(*_args, **kwargs):
        budgets.append(kwargs['timeout'])
        if not recover or len(budgets) == 1:
            raise subprocess.TimeoutExpired('PRIVATE_COMMAND', kwargs['timeout'])
    monkeypatch.setattr(brain, '_verify_codex_version', probe)
    with brain.codex_cycle_scope():
        for _ in range(3):
            if recover:
                brain.run_brain(request(), env={'BRAIN': 'codex'}, timeout_seconds=30)
            else:
                with pytest.raises(brain.BrainTransportError):
                    brain.run_brain(request(), env={'BRAIN': 'codex'}, timeout_seconds=30)
    assert len(budgets) == 2 and all(0 < budget <= 10 for budget in budgets)


def test_probe_retry_does_not_exceed_request_deadline(monkeypatch, tmp_path):
    runtime(monkeypatch, tmp_path)
    now, budgets = [0.0], []
    monkeypatch.setattr(brain.time, 'monotonic', lambda: now[0])
    def probe(*_args, **kwargs):
        budgets.append(kwargs['timeout'])
        now[0] += kwargs['timeout']
        raise subprocess.TimeoutExpired('codex', kwargs['timeout'])
    monkeypatch.setattr(brain, '_verify_codex_version', probe)
    with brain.codex_cycle_scope(), pytest.raises(brain.BrainTransportError):
        brain.run_brain(request(), env={'BRAIN': 'codex'}, timeout_seconds=3)
    assert budgets == [3]


def setup_cycle(monkeypatch, outcomes):
    claims = []
    monkeypatch.setattr(local_analysis, '_candidate_ids',
                        lambda _c, stage: list(outcomes.get(stage, {})))
    monkeypatch.setattr(local_analysis, 'claim', lambda _c, stage, item, *_a: claims.append((stage, item)) or 1)
    monkeypatch.setattr(local_analysis, 'complete', lambda *_a: True)
    monkeypatch.setattr(local_analysis, 'defer', lambda *_a: True)
    def stage(_connection, stage, item, _timeout, **_kwargs):
        outcome = outcomes[stage][item]
        with brain.provider_diagnostic_scope(lambda _event: None):
            return outcome() if callable(outcome) else outcome
    monkeypatch.setattr(local_analysis, '_run_stage', stage)
    return claims


def cycle():
    return local_analysis.run_cycle(object(), max_items=6, timeout_seconds=30,
                                    lease_seconds=90, worker_id='synthetic-worker',
                                    embeddings_enabled=False)


def summary(capsys):
    return json.loads(capsys.readouterr().out.splitlines()[-1])


def test_deferred_item_is_visited_once_per_stage_and_cycle(monkeypatch, capsys):
    claims = setup_cycle(monkeypatch, {'extract': {'same': 1}, 'score': {'same': 0}})
    assert cycle() == 1
    assert claims == [('extract', 'same'), ('score', 'same')]
    assert summary(capsys) == dict(event='summary', attempted=2, failed=1,
        distinct_items=1, completed=1, deferred=1, status='partial',
        timeouts_by_phase={'version_probe': 0, 'inference': 0})
    assert cycle() == 1
    assert claims == [('extract', 'same'), ('score', 'same')] * 2


@pytest.mark.parametrize('outcomes,status,exit_code,completed,deferred', [
    ({}, 'idle', 0, 0, 0),
    ({'extract': {'a': 0, 'b': 0}}, 'succeeded', 0, 2, 0),
    ({'extract': {'a': 1, 'b': 1}}, 'failed', 1, 0, 2),
    ({'extract': {'a': 1, 'b': 0}}, 'partial', 1, 1, 1),
])
def test_honest_cycle_summary_preserves_failure_exit(monkeypatch, capsys, outcomes, status, exit_code, completed, deferred):
    setup_cycle(monkeypatch, outcomes)
    assert cycle() == exit_code
    event = summary(capsys)
    assert event['status'] == status
    assert event['distinct_items'] == completed + deferred
    assert event['completed'] == completed and event['deferred'] == deferred
    assert event['failed'] == deferred


def test_cycle_scopes_probe_and_collects_nested_timeout_receipts(monkeypatch, tmp_path, capsys):
    def inference_timeout(command, **kwargs):
        raise subprocess.TimeoutExpired('codex', kwargs['timeout'])
    runtime(monkeypatch, tmp_path, inference_timeout)
    probes = []
    monkeypatch.setattr(brain, '_verify_codex_version', lambda *_a, **_k: probes.append(True))
    def run():
        try:
            brain.run_brain(request(), env={'BRAIN': 'codex'})
        except brain.BrainTransportError:
            return 1
    setup_cycle(monkeypatch, {'extract': {'a': run}, 'score': {'b': run}})
    assert cycle() == 1
    event = summary(capsys)
    assert len(probes) == 1
    assert event['timeouts_by_phase'] == {'version_probe': 0, 'inference': 2}
    assert cycle() == 1
    assert len(probes) == 2


def test_lease_lost_is_deferred_and_failed(monkeypatch, capsys):
    setup_cycle(monkeypatch, {'extract': {'a': 0}})
    monkeypatch.setattr(local_analysis, 'complete', lambda *_a: False)
    assert cycle() == 1
    event = summary(capsys)
    assert (event['completed'], event['deferred'], event['status']) == (0, 1, 'failed')


def test_missing_database_has_failed_summary(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv('DATABASE_URL', raising=False)
    monkeypatch.setattr('sys.argv', ['local-analysis', '--lock-file', str(tmp_path / 'lock')])
    assert local_analysis.main() == 1
    event = summary(capsys)
    assert event['status'] == 'failed'
    assert event['distinct_items'] == event['completed'] == event['deferred'] == 0


def test_cached_probe_timeout_is_not_counted_as_another_probe(monkeypatch, tmp_path, capsys):
    runtime(monkeypatch, tmp_path)
    probes, events = [], []
    def timeout(*_args, **kwargs):
        probes.append(True)
        raise subprocess.TimeoutExpired('PRIVATE', kwargs['timeout'])
    monkeypatch.setattr(brain, '_verify_codex_version', timeout)
    def run():
        with pytest.raises(brain.BrainTransportError):
            brain.run_brain(request(), env={'BRAIN': 'codex'})
        return 1
    setup_cycle(monkeypatch, {'extract': {'a': run, 'b': run}})
    with brain.provider_diagnostic_scope(events.append):
        assert cycle() == 1
    assert len(probes) == 2  # One probe plus its bounded retry.
    assert events[0].get('cached', False) is False
    assert events[1]['cached'] is True
    assert events[1]['phase_elapsed_ms'] == events[1]['phase_timeout_seconds'] == 0
    assert summary(capsys)['timeouts_by_phase'] == {'version_probe': 1, 'inference': 0}


def test_fatal_error_preserves_progress_and_does_not_invent_deferrals(monkeypatch, capsys):
    setup_cycle(monkeypatch, {'extract': {'a': 0}})
    scans = []
    def candidates(_connection, stage):
        scans.append(stage)
        if len(scans) > 1:
            raise ConnectionError('PRIVATE_DATABASE_URL')
        return ['a']
    monkeypatch.setattr(local_analysis, '_candidate_ids', candidates)
    assert cycle() == 1
    event = summary(capsys)
    assert (event['attempted'], event['distinct_items'], event['completed']) == (1, 1, 1)
    assert (event['failed'], event['deferred'], event['status']) == (1, 0, 'partial')
    assert event['failure'] == 'ConnectionError'
    assert 'PRIVATE' not in json.dumps(event)


def test_probe_launch_failure_is_cached_only_for_this_cycle(monkeypatch, tmp_path):
    runtime(monkeypatch, tmp_path)
    probes = []
    def unavailable(*_args, **_kwargs):
        probes.append(True)
        raise OSError('PRIVATE_PATH')
    monkeypatch.setattr(brain, '_verify_codex_version', unavailable)
    for _ in range(2):
        with brain.codex_cycle_scope():
            for _ in range(2):
                with pytest.raises(brain.BrainTransportError) as caught:
                    brain.run_brain(request(), env={'BRAIN': 'codex'})
                assert caught.value.category == 'launch_error'
    assert len(probes) == 2
