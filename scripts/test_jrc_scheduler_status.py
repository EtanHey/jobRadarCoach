import json
from pathlib import Path
import runpy
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(('state', 'scheduler_code', 'runtime_code', 'expected'), [
    ('healthy', 0, 0, 0), ('running', 0, 0, 0),
    ('failed', 1, 0, 1), ('healthy', 0, 1, 1), ('healthy', 1, 0, 1),
])
def test_status_combines_scheduler_and_voice_health(monkeypatch, capsys, state,
                                                   scheduler_code, runtime_code, expected):
    namespace = runpy.run_path(str(ROOT / 'jrc'))
    calls = []

    def run(args, **kwargs):
        calls.append((args, kwargs))
        return subprocess.CompletedProcess(args, scheduler_code,
                                           json.dumps({'state': state, 'reason': None}), '')

    monkeypatch.setattr(subprocess, 'run', run)
    monkeypatch.setattr(subprocess, 'call', lambda args: runtime_code)
    assert namespace['main'](['status']) == expected
    assert f'scheduler: {state}' in capsys.readouterr().out
    assert calls[0][0][-1] == str(ROOT / 'scripts/pipeline_scheduler_status.py')
    assert calls[0][1]['timeout'] == 15


def test_status_failure_does_not_hide_runtime_or_expose_error_text(monkeypatch, capsys):
    namespace = runpy.run_path(str(ROOT / 'jrc'))
    seen = []

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired('private command contents', 15)

    monkeypatch.setattr(subprocess, 'run', timeout)
    monkeypatch.setattr(subprocess, 'call', lambda args: seen.append(args) or 0)
    assert namespace['main'](['status']) == 1
    assert seen and seen[0][-1] == 'status'
    assert capsys.readouterr().out == 'scheduler: unknown (StatusUnavailable)\n'
