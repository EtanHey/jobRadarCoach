from types import SimpleNamespace

import pytest

from scripts.runtime_control import _identity_alive
from scripts.runtime_process import RuntimeContext


@pytest.mark.parametrize('running', [True, False])
def test_container_identity_uses_adapter_liveness(tmp_path, running):
    identity = {'container_id': 'exact-container', 'started_at': 'exact-start'}
    context = RuntimeContext(tmp_path, tmp_path / 'state')
    seen = []

    def observe(current_context, current_identity):
        seen.append((current_context, current_identity))
        return running

    assert _identity_alive(context, SimpleNamespace(is_running=observe), identity) is running
    assert seen == [(context, identity)]


@pytest.mark.parametrize('observation', [None, 'false', 0])
def test_ambiguous_resource_observation_is_not_reported_as_dead(tmp_path, observation):
    service = SimpleNamespace(is_running=lambda *_args: observation)
    assert _identity_alive(RuntimeContext(tmp_path, tmp_path / 'state'), service, {}) is None


def test_missing_or_failed_resource_probe_is_not_reported_as_dead(tmp_path):
    context = RuntimeContext(tmp_path, tmp_path / 'state')
    assert _identity_alive(context, SimpleNamespace(), {'deployment_uid': 'uid'}) is None

    def unavailable(*_args):
        raise OSError('API unavailable')

    assert _identity_alive(context, SimpleNamespace(is_running=unavailable), {}) is None
