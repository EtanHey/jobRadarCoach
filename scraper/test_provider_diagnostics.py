import json
import subprocess
import sys

import pytest

from scraper import brain
from scraper.codex_process import run_codex_process
from scraper.test_codex_brain import install_runtime, request


@pytest.mark.parametrize('mode,category', [('exit', 'nonzero_exit'), ('timeout', 'timeout'),
                                          ('launch', 'launch_error'), ('success', 'success')])
def test_safe_request_receipt(monkeypatch, tmp_path, mode, category):
    def process(command, **kwargs):
        if mode == 'timeout':
            raise subprocess.TimeoutExpired('PRIVATE_COMMAND', 2, stderr='PRIVATE_TOKEN')
        if mode == 'launch':
            raise OSError('PRIVATE_PATH')
        if mode == 'exit':
            return subprocess.CompletedProcess(command, 7)
        from pathlib import Path
        Path(command[command.index('--output-last-message') + 1]).write_text(
            '{"role_family":"backend","mentions_typescript":true}')
        return subprocess.CompletedProcess(command, 0)
    install_runtime(monkeypatch, tmp_path, process)
    events = []
    with brain.provider_diagnostic_scope(events.append):
        try:
            brain.run_brain(request(), env={'BRAIN': 'codex', 'CODEX_MODEL': 'PRIVATE_MODEL'}, timeout_seconds=2)
        except brain.BrainError:
            pass
    assert len(events) == 1
    event = events[0]
    assert event['category'] == category
    assert event['provider'] == 'codex' and event['model'] == 'configured'
    assert event['elapsed_ms'] >= 0 and event['timeout_seconds'] == 2
    assert event['exit_code'] == (7 if mode == 'exit' else None)
    assert 'PRIVATE' not in json.dumps(event)
    assert request().prompt not in json.dumps(event)


@pytest.mark.parametrize('message,category', [('usage_limit_reached', 'quota'),
    ('401 Unauthorized', 'auth'), ('model_not_found', 'model_access'), ('unrecognized failure', 'nonzero_exit')])
def test_real_child_classifies_only_bounded_terminal_error(tmp_path, message, category):
    code = 'import sys; sys.stdin.read(); sys.stderr.write("PRIVATE_PROMPT\\nERROR: " + sys.argv[1] + " PRIVATE_SECRET\\n"); sys.exit(1)'
    result = run_codex_process([sys.executable, '-c', code, message], stdin_text='x' * 32000,
        text=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=2, cwd=tmp_path, env={})
    assert result.returncode == 1
    assert result.stderr == {'category': category, 'truncated': False}
    assert 'PRIVATE' not in json.dumps(result.stderr)


def test_real_child_drains_stderr_flood_without_retaining_or_blocking(tmp_path, monkeypatch):
    from scraper import codex_process
    classify = codex_process._stderr_category
    def bounded(raw, truncated):
        assert len(raw) <= codex_process.MAX_STDERR_BYTES
        return classify(raw, truncated)
    monkeypatch.setattr(codex_process, '_stderr_category', bounded)
    code = 'import sys; sys.stderr.write("PRIVATE_SECRET" * 100000); sys.stderr.flush(); sys.stdin.read(); sys.exit(1)'
    result = run_codex_process([sys.executable, '-c', code], stdin_text='x' * 32000,
        text=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=3, cwd=tmp_path, env={})
    assert result.stderr == {'category': 'nonzero_exit', 'truncated': True}


def test_capture_timeout_still_kills_descendant(tmp_path):
    from scraper.test_codex_process import running
    pid_file = tmp_path / 'pid'
    code = 'import subprocess,sys,time; from pathlib import Path; p=subprocess.Popen([sys.executable,"-c","import time; time.sleep(60)"]); Path(sys.argv[1]).write_text(str(p.pid)); sys.stderr.write("PRIVATE_SECRET"); time.sleep(60)'
    with pytest.raises(subprocess.TimeoutExpired):
        run_codex_process([sys.executable, '-c', code, str(pid_file)], stdin_text='',
            text=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=.5, cwd=tmp_path, env={})
    assert not running(int(pid_file.read_text()))


@pytest.mark.parametrize('stage', ['extract', 'score'])
def test_request_event_reaches_both_batch_logs(monkeypatch, tmp_path, capsys, stage):
    from extractor import job as extraction
    from extractor.test_job import Connection as ExtractConnection
    from classifier import job as scoring
    from classifier.test_job import Connection as ScoreConnection
    install_runtime(monkeypatch, tmp_path, lambda *_args, **_kwargs: subprocess.CompletedProcess([], 7))
    def extract(*_args, **_kwargs):
        brain.run_brain(request(), env={'BRAIN': 'codex'}, timeout_seconds=2)
    def score(_connection, _id, *, brain_runner):
        brain_runner(request(), {})
    if stage == 'extract':
        status = extraction.run_batch(ExtractConnection(), limit=1, timeout_seconds=2, extractor=extract)
    else:
        status = scoring.run_batch(ScoreConnection(), limit=1, timeout_seconds=2,
                                  candidate_lister=lambda *_a, **_k: ['00000000-0000-0000-0000-000000000001'],
                                  scorer=score, brain=brain.run_brain)
    records = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    events = [r for r in records if r.get('event') == 'provider_request']
    assert status == 1 and len(events) == 1
    assert events[0]['category'] == 'nonzero_exit' and events[0]['exit_code'] == 7


def test_invalid_config_observer_and_context_reset_do_not_change_outcome(monkeypatch, tmp_path, capsys):
    install_runtime(monkeypatch, tmp_path, lambda *_a, **_k: subprocess.CompletedProcess([], 7))
    events = []
    with brain.provider_diagnostic_scope(events.append):
        with pytest.raises(brain.BrainConfigurationError):
            brain.run_brain(request(), env={'BRAIN': 'codex', 'CODEX_MODEL': ['PRIVATE_SECRET']})
    assert events[0]['category'] == 'configuration_error' and 'PRIVATE' not in json.dumps(events)
    with pytest.raises(brain.BrainTransportError):
        brain.run_brain(request(), env={'BRAIN': 'codex'})
    assert len(events) == 1 and not capsys.readouterr().out
    with brain.provider_diagnostic_scope(lambda _event: (_ for _ in ()).throw(RuntimeError('PRIVATE_CALLBACK'))):
        with pytest.raises(brain.BrainTransportError):
            brain.run_brain(request(), env={'BRAIN': 'codex'})


def test_terminal_error_survives_long_prompt_echo(tmp_path):
    code = 'import sys; sys.stdin.read(); sys.stderr.write("PRIVATE_PROMPT" * 10000 + "\\nERROR: usage_limit_reached PRIVATE_SECRET\\n"); sys.exit(1)'
    result = run_codex_process([sys.executable, '-c', code], stdin_text='', text=True,
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=2, cwd=tmp_path, env={})
    assert result.stderr == {'category': 'quota', 'truncated': True}


def test_parent_exit_does_not_wait_for_descendant_stderr(tmp_path):
    import time
    from scraper.test_codex_process import running
    pid_file = tmp_path / 'pid'
    code = 'import subprocess,sys; from pathlib import Path; p=subprocess.Popen([sys.executable,"-c","import time; time.sleep(60)"]); Path(sys.argv[1]).write_text(str(p.pid)); sys.stderr.write("ERROR: 401 Unauthorized\\n"); sys.exit(1)'
    started = time.monotonic()
    result = run_codex_process([sys.executable, '-c', code, str(pid_file)], stdin_text='',
        text=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=2, cwd=tmp_path, env={})
    assert result.returncode == 1 and result.stderr['category'] == 'auth'
    assert time.monotonic() - started < 1 and not running(int(pid_file.read_text()))


def test_receipt_uses_normalized_runtime_model_and_effort(monkeypatch, tmp_path):
    install_runtime(monkeypatch, tmp_path, lambda *_a, **_k: subprocess.CompletedProcess([], 7))
    events = []
    with brain.provider_diagnostic_scope(events.append), pytest.raises(brain.BrainTransportError):
        brain.run_brain(request(), env={'BRAIN': 'codex', 'CODEX_MODEL': ' gpt-5.6-terra ', 'CODEX_REASONING_EFFORT': ' XHIGH '})
    assert events[0]['model'] == 'gpt-5.6-terra' and events[0]['reasoning_effort'] == 'xhigh'


def test_parent_exit_tears_down_group_once(monkeypatch, tmp_path):
    from scraper import codex_process
    from scraper.test_codex_process import running
    import os
    pidfile = tmp_path / 'child.pid'
    code = ('import subprocess,sys;from pathlib import Path;'
            'p=subprocess.Popen([sys.executable,"-c","import time;time.sleep(60)"]);'
            'Path(sys.argv[1]).write_text(str(p.pid));sys.exit(0)')
    original = codex_process._stop_group
    calls = []

    def stop(process):
        calls.append(process.pid)
        assert len(calls) == 1, 'group teardown repeated after parent exit'
        original(process)

    monkeypatch.setattr(codex_process, '_stop_group', stop)
    try:
        result = run_codex_process([sys.executable, '-c', code, str(pidfile)], stdin_text='',
            text=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=2, cwd=tmp_path, env={})
        assert result.returncode == 0 and len(calls) == 1
        assert not running(int(pidfile.read_text()))
    finally:
        if pidfile.exists() and running(int(pidfile.read_text())):
            os.kill(int(pidfile.read_text()), 9)


@pytest.mark.parametrize('stage', ['extractor', 'scorer'])
def test_receipt_allowlist_follows_stage_policy_in_fresh_process(stage):
    # A stage default update must reach receipts; arbitrary configured models stay private.
    code = '''
import json
from scraper import stage_config
setattr(stage_config, STAGE.upper() + '_MODEL', 'synthetic-public-default')
from scraper import brain
brain._run_brain = lambda *a, **k: None
events = []
with brain.provider_diagnostic_scope(events.append):
    for model in ['synthetic-public-default', 'PRIVATE_CUSTOM_MODEL', brain.DEFAULT_CODEX_MODEL]:
        brain.run_brain(None, env={'BRAIN': 'codex', 'CODEX_MODEL': model})
print(json.dumps([event['model'] for event in events]))
'''.replace('STAGE', repr(stage))
    completed = subprocess.run([sys.executable, '-c', code], check=True,
                               capture_output=True, text=True)
    assert json.loads(completed.stdout) == ['synthetic-public-default', 'configured', brain.DEFAULT_CODEX_MODEL]
