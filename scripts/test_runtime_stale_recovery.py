"""Recover an abruptly killed supervisor using its recorded ownership and mode."""
import json
import os
from pathlib import Path
import signal
import subprocess

import pytest

from test_support.runtime_cli_support import ROOT, environment, is_alive, wait_for
from test_support.runtime_supervisor_services import _service


class ModeService:
    name = 'worker'

    def __init__(self, directory):
        self.directory = directory
        self.service = _service(self.name, directory / 'worker.pid')

    def probe(self, context):
        return self.service.probe(context)

    def start(self, context):
        return self.service.start(context)

    def owns(self, context, identity):
        return self.service.owns(context, identity)

    def stop(self, context, identity):
        self.service.stop(context, identity)
        with (self.directory / 'stopped-modes').open('a') as output:
            output.write('qa\n' if context.qa_mode else 'normal\n')


def build_services(_context):
    return [ModeService(Path(os.environ['TEST_MARKER']).parent)]


@pytest.mark.parametrize('command', ['run', 'down'])
def test_crashed_supervisor_recovers_exact_owned_child_in_original_mode(tmp_path, command):
    env = environment(tmp_path)
    env['RUN_SERVICES_MODULE'] = 'scripts.test_runtime_stale_recovery'
    log = (tmp_path / 'supervisor.log').open('w')
    owner = subprocess.Popen([str(ROOT / 'jrc'), 'run', '--qa'], env=env, cwd=ROOT,
                             stdout=log, stderr=subprocess.STDOUT)
    state_path = tmp_path / 'state/state.json'
    replacement = None
    identities = []
    try:
        wait_for(lambda: state_path.exists() and bool(json.loads(state_path.read_text())['services']))
        state = json.loads(state_path.read_text())
        identity = state['services'][0]['identity']
        identities.append(identity)
        owner.kill()
        owner.wait(timeout=5)
        assert is_alive(identity['pid'])
        replacement = subprocess.Popen([str(ROOT / 'jrc'), command], env=env, cwd=ROOT,
                                       stdout=log, stderr=subprocess.STDOUT)
        if command == 'run':
            wait_for(lambda: state_path.exists() and bool(json.loads(state_path.read_text())['services'])
                     and json.loads(state_path.read_text())['supervisor']['pid'] == replacement.pid)
            restarted = json.loads(state_path.read_text())
            identities.append(restarted['services'][0]['identity'])
            assert restarted['qa_mode'] is False
            assert identities[-1]['pid'] != identity['pid']
            assert not is_alive(identity['pid'])
            replacement.send_signal(signal.SIGINT)
        assert replacement.wait(timeout=5) == 0
        assert not state_path.exists()
        modes = (tmp_path / 'stopped-modes').read_text().splitlines()
        assert modes == (['qa', 'normal'] if command == 'run' else ['qa'])
        assert all(not is_alive(item['pid']) for item in identities)
    finally:
        for process in [owner, replacement]:
            if process is not None and process.poll() is None:
                process.terminate()
                process.wait(timeout=5)
        log.close()
        # Emergency cleanup remains fenced by the same recorded process identities.
        from scripts.runtime_process import RuntimeContext
        service = _service('worker', tmp_path / 'worker.pid')
        context = RuntimeContext(ROOT, tmp_path / 'state')
        for item in identities:
            if service.owns(context, item):
                service.stop(context, item)
