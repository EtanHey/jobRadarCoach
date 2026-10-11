"""Execute the scheduled jobs' alert path with synthetic receipts."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.parametrize(('kind', 'receipt', 'message'), [
    ('scrape', {'status': 'success', 'result': {'source_warning_count': 1}}, '1 source failure'),
    ('scrape', {'status': 'failure', 'error': 'secret-value'}, 'run failed'),
    ('liveness', {'status': 'success', 'alerts': 1}, '1 new uncertainty'),
    ('liveness', {'status': 'failure', 'error': 'secret-value'}, 'run failed'),
    ('liveness', None, 'receipt missing'),
    ('scrape', 'malformed', 'receipt invalid'),
    ('scrape', {'status': 'success'}, 'receipt invalid'),
    ('scrape', {'status': 'success', 'result': {}}, 'receipt invalid'),
    ('scrape', {'status': 'success', 'result': [], 'alerts': 0}, 'receipt invalid'),
    ('liveness', {'status': 'success'}, 'receipt invalid'),
])
def test_first_failure_is_visible_without_replaying_private_receipt(tmp_path, kind, receipt, message):
    path = tmp_path / 'receipt.json'
    if receipt is not None:
        path.write_text(json.dumps(receipt) if receipt != 'malformed' else '{')
    result = subprocess.run([sys.executable, '-m', 'scraper.run_alerts', '--kind', kind,
                             '--receipt', str(path)], capture_output=True, text=True,
                            env={**os.environ, 'GITHUB_ACTIONS': 'true'})
    assert result.returncode == 0
    assert '::warning::' in result.stdout and message in result.stdout
    assert 'secret-value' not in result.stdout + result.stderr


@pytest.mark.parametrize('kind', ['scrape', 'liveness'])
@pytest.mark.parametrize('count', [None, True, False, -1, 0.0, '0', [], {}])
def test_invalid_counter_never_passes_as_healthy(tmp_path, kind, count):
    receipt = {'status': 'success', 'private': 'secret-value'}
    if kind == 'scrape':
        receipt['result'] = {'source_warning_count': count}
        receipt['alerts'] = 0  # A valid counter for the other kind cannot rescue it.
    else:
        receipt['alerts'] = count
        receipt['result'] = {'source_warning_count': 0}
    test_first_failure_is_visible_without_replaying_private_receipt(
        tmp_path, kind, receipt, 'receipt invalid')


@pytest.mark.parametrize('result', [None, False, 0, 'secret-value', []])
def test_scrape_requires_an_object_result(tmp_path, result):
    test_first_failure_is_visible_without_replaying_private_receipt(
        tmp_path, 'scrape', {'status': 'success', 'result': result, 'alerts': 0},
        'receipt invalid')


@pytest.mark.parametrize('kind', ['scrape', 'liveness'])
def test_healthy_run_emits_no_alert(tmp_path, kind):
    path = tmp_path / 'receipt.json'
    receipt = ({'status': 'success', 'result': {'source_warning_count': 0}}
               if kind == 'scrape' else {'status': 'success', 'alerts': 0})
    path.write_text(json.dumps(receipt))
    result = subprocess.run([sys.executable, '-m', 'scraper.run_alerts', '--kind', kind,
                             '--receipt', str(path)], capture_output=True, text=True)
    assert result.returncode == 0 and not result.stdout and not result.stderr


def test_both_workflows_execute_same_alert_path_even_after_failure():
    workflows = Path(__file__).parents[1] / '.github/workflows'
    for name, kind in [('cloud-scrape.yml', 'scrape'), ('ats-liveness.yml', 'liveness')]:
        text = (workflows / name).read_text()
        step = next(s for s in text.split('      - name:') if 'scraper.run_alerts' in s)
        assert 'if: always()' in step and f'--kind {kind}' in step
