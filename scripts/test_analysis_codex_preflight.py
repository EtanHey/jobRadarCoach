from pathlib import Path

import pytest

from scripts.analysis_codex_preflight import check_pin


def binary(path, version):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('#!/bin/sh\nprintf "codex-cli ' + version + '\\n"\n')
    path.chmod(0o755)
    return path


def test_installed_pin_vs_latest_is_loud(tmp_path, capsys):
    pinned = binary(tmp_path / 'releases/0.153.4-aarch64-apple-darwin/bin/codex', '0.153.4')
    binary(tmp_path / 'releases/0.160.1-aarch64-apple-darwin/bin/codex', '0.160.1')
    check_pin(pinned, 'codex-cli 0.153.4', tmp_path)
    output = capsys.readouterr()
    assert 'installed=0.153.4' in output.out and 'latest_standalone=0.160.1' in output.out
    assert 'STALE' in output.err


def test_missing_pin_fails_loudly_before_install(tmp_path, capsys):
    with pytest.raises(RuntimeError, match='pinned Codex binary is missing'):
        check_pin(tmp_path / 'absent', 'codex-cli 0.153.4', tmp_path)


def test_wrong_binary_version_is_rejected(tmp_path):
    pinned = binary(tmp_path / 'codex', '0.160.1')
    with pytest.raises(RuntimeError, match='does not match'):
        check_pin(pinned, 'codex-cli 0.153.4', tmp_path)


def test_wrapper_refuses_missing_pin_before_backend(tmp_path):
    import os
    import plistlib
    import shutil
    import subprocess
    for name in ('analysis_codex_preflight.py', 'install-local-analysis.sh'):
        target = tmp_path / 'scripts' / name
        target.parent.mkdir(exist_ok=True)
        shutil.copyfile(Path('scripts') / name, target)
    marker = tmp_path / 'installed'
    backend = tmp_path / 'docs.local/tools/local-analysis-tool.py'
    backend.parent.mkdir(parents=True)
    backend.write_text(f'from pathlib import Path\nPath({str(marker)!r}).touch()\n')
    pinned = tmp_path / '.codex/packages/standalone/releases/0.153.4-aarch64-apple-darwin/bin/codex'
    plist = tmp_path / 'Library/LaunchAgents/com.jobradarcoach.local-analysis.plist'
    plist.parent.mkdir(parents=True)
    plist.write_bytes(plistlib.dumps({'EnvironmentVariables': {'CODEX': str(pinned)}}))
    cmd = ['bash', str(tmp_path / 'scripts/install-local-analysis.sh'), 'master', '--repo', str(Path.cwd())]
    env = dict(os.environ, HOME=str(tmp_path))
    failed = subprocess.run(cmd, env=env, capture_output=True, text=True)
    assert failed.returncode and not marker.exists() and 'CODEX_PIN BLOCKED' in failed.stderr
    binary(pinned, '0.153.4')
    passed = subprocess.run(cmd, env=env, capture_output=True, text=True)
    assert passed.returncode == 0 and marker.exists() and 'installed=0.153.4' in passed.stdout


def test_missing_source_pin_has_explicit_diagnostic(monkeypatch):
    import subprocess
    from scripts import analysis_codex_preflight as preflight
    monkeypatch.setattr('sys.argv', ['preflight', '1234567'])
    monkeypatch.setattr(preflight.subprocess, 'run', lambda *_a, **_k: subprocess.CompletedProcess([], 0, stdout=b'# no pin'))
    with pytest.raises(RuntimeError, match='source Codex pin is invalid'):
        preflight.main()
