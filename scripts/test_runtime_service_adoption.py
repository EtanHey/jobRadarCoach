"""Explicit lifecycle adoption must preserve ordinary borrowed processes."""
import json
import os
from pathlib import Path
import signal
import subprocess
import threading

from scripts.runtime_process import RuntimeContext
from test_support.runtime_cli_support import ROOT, environment, is_alive, wait_for
from test_support.runtime_supervisor_services import _service


class AdoptedProcess:
    lifecycle_owned = True

    def __init__(self, directory):
        self.name = 'adopted'
        self.directory = directory
        self.service = _service(self.name, directory / 'adopted.pid')

    def probe(self, context):
        return self.service.probe(context)

    def start(self, context):
        identity = json.loads((self.directory / 'identity.json').read_text())
        if not self.service.owns(context, identity) or not self.probe(context).healthy:
            raise RuntimeError('adoption identity is unavailable')
        (self.directory / 'adopted.receipt').write_text(str(identity['pid']))
        return identity

    def owns(self, context, identity):
        return self.service.owns(context, identity)

    def stop(self, context, identity):
        self.service.stop(context, identity)


def build_services(_context):
    directory = Path(os.environ['TEST_MARKER']).parent
    return [AdoptedProcess(directory), _service('borrowed', directory / 'borrowed.pid')]


def test_running_explicit_service_is_adopted_and_borrowed_process_survives(tmp_path):
    context = RuntimeContext(ROOT, tmp_path / 'fixture-state')
    adopted = _service('adopted', tmp_path / 'adopted.pid')
    borrowed = _service('borrowed', tmp_path / 'borrowed.pid')
    identity = adopted.start(context)
    borrowed_identity = borrowed.start(context)
    threading.Thread(target=adopted._children[identity['pid']].wait, daemon=True).start()
    (tmp_path / 'identity.json').write_text(json.dumps(identity))
    env = environment(tmp_path)
    env['RUN_SERVICES_MODULE'] = 'scripts.test_runtime_service_adoption'
    log = (tmp_path / 'supervisor.log').open('w')
    owner = subprocess.Popen([str(ROOT / 'jrc'), 'run'], cwd=ROOT, env=env,
                             stdout=log, stderr=subprocess.STDOUT)
    state = tmp_path / 'state/state.json'
    try:
        wait_for(lambda: state.exists() and len(json.loads(state.read_text())['services']) == 2)
        rows = json.loads(state.read_text())['services']
        assert [row['mode'] for row in rows] == ['owned', 'borrowed']
        assert rows[0]['identity']['pid'] == identity['pid']
        assert (tmp_path / 'adopted.receipt').read_text() == str(identity['pid'])
        owner.send_signal(signal.SIGINT)
        assert owner.wait(timeout=5) == 0
        assert not is_alive(identity['pid'])
        assert is_alive(borrowed_identity['pid'])
    finally:
        if owner.poll() is None:
            owner.terminate()
            owner.wait(timeout=5)
        log.close()
        try:
            adopted._children[identity["pid"]].poll()
            adopted.stop(context, identity)
        finally:
            borrowed.stop(context, borrowed_identity)
