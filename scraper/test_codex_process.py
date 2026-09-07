import json
import os
import subprocess
import sys
import time

import pytest

from scraper.brain import _run_codex_process as run_codex_process, _verify_codex_version as verify_codex_version


def running(pid):
    result = subprocess.run(['ps', '-p', str(pid), '-o', 'stat='], capture_output=True, text=True, check=False)
    return bool(result.stdout.strip()) and not result.stdout.strip().startswith('Z')


def test_timeout_stops_descendant(tmp_path):
    pid_file = tmp_path / 'child.pid'
    code = "import subprocess,sys,time; from pathlib import Path; p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']); Path(sys.argv[1]).write_text(str(p.pid)); time.sleep(60)"
    try:
        with pytest.raises(subprocess.TimeoutExpired):
            run_codex_process([sys.executable, '-c', code, str(pid_file)], stdin_text='', text=True,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                              timeout=0.5, cwd=tmp_path, env={})
        child = int(pid_file.read_text())
        deadline = time.monotonic() + 2
        while running(child) and time.monotonic() < deadline:
            time.sleep(0.02)
        assert not running(child)
    finally:
        if pid_file.exists() and running(int(pid_file.read_text())):
            os.kill(int(pid_file.read_text()), 9)


def executable(tmp_path, body):
    path = tmp_path / 'codex'
    path.write_text(f'#!{sys.executable}\n'+body)
    path.chmod(0o755)
    return str(path)


def test_version_probe_environment_and_output_bound(tmp_path, monkeypatch):
    sentinel = 'PRIVATE_VERSION_PROBE'
    monkeypatch.setenv(sentinel, 'secret')
    record = tmp_path / 'environment.json'
    path = executable(tmp_path, f'import os,json\nfrom pathlib import Path\nPath({str(record)!r}).write_text(json.dumps(dict(os.environ)))\nprint("codex-cli 0.153.4")\n')
    verify_codex_version(path, cwd=tmp_path, env={'HOME': str(tmp_path)}, timeout=1)
    assert sentinel not in json.loads(record.read_text())
    path = executable(tmp_path, 'import sys,time\nsys.stdout.write("x"*10000);sys.stdout.flush();time.sleep(60)\n')
    started = time.monotonic()
    with pytest.raises(RuntimeError, match='bounded version'):
        verify_codex_version(path, cwd=tmp_path, env={}, timeout=1)
    assert time.monotonic() - started < 2


def test_version_probe_obeys_small_timeout(tmp_path):
    path = executable(tmp_path, 'import time\ntime.sleep(60)\n')
    with pytest.raises(subprocess.TimeoutExpired):
        verify_codex_version(path, cwd=tmp_path, env={}, timeout=0.1)
