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
def test_healthy_run_emits_no_alert(tmp_path, kind):
    path = tmp_path / 'receipt.json'
    path.write_text(json.dumps({'status': 'success', 'result': {'source_warning_count': 0}, 'alerts': 0}))
    result = subprocess.run([sys.executable, '-m', 'scraper.run_alerts', '--kind', kind,
                             '--receipt', str(path)], capture_output=True, text=True)
    assert result.returncode == 0 and not result.stdout and not result.stderr


def test_both_workflows_execute_same_alert_path_even_after_failure():
    workflows = Path(__file__).parents[1] / '.github/workflows'
    for name, kind in [('cloud-scrape.yml', 'scrape'), ('ats-liveness.yml', 'liveness')]:
        text = (workflows / name).read_text()
        step = next(s for s in text.split('      - name:') if 'scraper.run_alerts' in s)
        assert 'if: always()' in step and f'--kind {kind}' in step
