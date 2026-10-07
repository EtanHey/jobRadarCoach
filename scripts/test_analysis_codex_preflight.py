from pathlib import Path
import os
import subprocess
import sys
import time

import pytest

from scripts.analysis_codex_preflight import check_pin
from scripts import analysis_codex_preflight as preflight


def synthetic_binary(tmp_path, body):
    path = tmp_path / 'synthetic-codex'
    path.write_text(f'#!{sys.executable}\n' + body)
    path.chmod(0o755)
    return path


def running(pid):
    status = subprocess.run(['ps', '-p', str(pid), '-o', 'stat='], capture_output=True, text=True).stdout.strip()
    return bool(status) and not status.startswith('Z')


def test_version_stdout_is_bounded_while_reading(tmp_path, monkeypatch):
    pinned = synthetic_binary(tmp_path, 'import os,time\nos.write(1,b"x"*1048576)\ntime.sleep(60)\n')
    read_sizes = []
    stdout_fd = None
    original = os.read
    original_popen = subprocess.Popen

    def popen(*args, **kwargs):
        nonlocal stdout_fd
        process = original_popen(*args, **kwargs)
        stdout_fd = process.stdout.fileno()
        return process

    def read(fd, size):
        if fd == stdout_fd:
            read_sizes.append(size)
        return original(fd, size)

    monkeypatch.setattr(preflight.os, 'read', read)
    monkeypatch.setattr(preflight.subprocess, 'Popen', popen)
    started = time.monotonic()
    with pytest.raises(RuntimeError, match='bounded version output'):
        check_pin(pinned, 'codex-cli 0.153.4', tmp_path)
    assert time.monotonic() - started < 2
    assert read_sizes and max(read_sizes) <= 1025


@pytest.mark.parametrize('mode', ['success', 'success_inherited_stdout', 'nonzero', 'overflow', 'timeout'])
def test_version_probe_kills_descendants_and_reaps_parent(tmp_path, monkeypatch, mode):
    pidfile = tmp_path / 'child.pid'
    actions = {
        'success': 'print("codex-cli 0.153.4",flush=True)',
        'success_inherited_stdout': 'print("codex-cli 0.153.4",flush=True)',
        'nonzero': 'sys.exit(2)',
        'overflow': 'os.write(1,b"x"*1048576)',
        'timeout': 'time.sleep(60)',
    }
    child_stdout = 'None' if mode == 'success_inherited_stdout' else 'subprocess.DEVNULL'
    pinned = synthetic_binary(tmp_path, 'import os,subprocess,sys,time\nfrom pathlib import Path\n'
        'child=subprocess.Popen([sys.executable,"-c","import time;time.sleep(60)"],'
        f'stdout={child_stdout},stderr=subprocess.DEVNULL)\n'
        f'Path({str(pidfile)!r}).write_text(str(child.pid))\n' + actions[mode] + '\n')
    parents = []
    original = subprocess.Popen

    def popen(*args, **kwargs):
        process = original(*args, **kwargs)
        parents.append(process)
        return process

    monkeypatch.setattr(preflight.subprocess, 'Popen', popen)
    # Allow interpreter startup under the shared queue's system load.
    monkeypatch.setattr(preflight, 'VERSION_TIMEOUT', 2, raising=False)
    try:
        if mode.startswith('success'):
            check_pin(pinned, 'codex-cli 0.153.4', tmp_path)
        else:
            with pytest.raises(RuntimeError):
                check_pin(pinned, 'codex-cli 0.153.4', tmp_path)
        child = int(pidfile.read_text())
        deadline = time.monotonic() + 2
        while running(child) and time.monotonic() < deadline:
            time.sleep(0.02)
        assert not running(child), f'{mode} left a version-probe descendant running'
        assert parents[0].returncode is not None
        with pytest.raises(ChildProcessError):
            os.waitpid(parents[0].pid, os.WNOHANG)
    finally:
        if pidfile.exists() and running(int(pidfile.read_text())):
            os.kill(int(pidfile.read_text()), 9)


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
    # Hosted PR checkouts need not fetch origin/master. Use the concrete tested source.
    sha = subprocess.run(['git', 'rev-parse', 'HEAD'], capture_output=True, text=True, check=True).stdout.strip()
    cmd = ['bash', str(tmp_path / 'scripts/install-local-analysis.sh'), sha, '--repo', str(Path.cwd())]
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
