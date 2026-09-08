import json
import os
from pathlib import Path
import signal
import subprocess

from test_support.runtime_cli_support import ROOT, environment, is_alive, run_entry, wait_for
from test_support.runtime_supervisor_services import _service


class _CountingStop:
    def __init__(self, service, directory: Path, fail_once: bool) -> None:
        self.service, self.name = service, service.name
        self.counter = directory / f"{self.name}.stops"
        self.starts = directory / f"{self.name}.starts"
        self.fail_once = fail_once

    def probe(self, context):
        return self.service.probe(context)

    def start(self, context):
        count = int(self.starts.read_text()) + 1 if self.starts.exists() else 1
        self.starts.write_text(str(count))
        return self.service.start(context)

    def owns(self, context, identity):
        return self.service.owns(context, identity)

    def stop(self, context, identity):
        count = int(self.counter.read_text()) + 1 if self.counter.exists() else 1
        self.counter.write_text(str(count))
        if self.fail_once and count == 1:
            raise RuntimeError("synthetic first stop failure")
        self.service.stop(context, identity)


def build_services(context):
    directory = Path(os.environ["TEST_MARKER"]).parent
    with (directory / "contexts").open("a") as handle:
        handle.write("qa\n" if context.qa_mode else "normal\n")
    return [
        _CountingStop(_service("first", directory / "first.pid"), directory, True),
        _CountingStop(_service("second", directory / "second.pid"), directory, False),
    ]


def _launch_partial(tmp_path):
    env = environment(tmp_path)
    env["RUN_SERVICES_MODULE"] = "scripts.test_runtime_cleanup_recovery"
    output_path = tmp_path / "supervisor.log"
    with output_path.open("w") as output:
        owner = subprocess.Popen(
            [str(ROOT / "run"), "up", "--qa"], cwd=ROOT, env=env,
            stdout=output, stderr=subprocess.STDOUT, text=True,
        )
    state_path = tmp_path / "state/state.json"
    wait_for(lambda: state_path.exists() and len(json.loads(state_path.read_text())["services"]) == 2)
    identities = {
        row["name"]: row["identity"] for row in json.loads(state_path.read_text())["services"]
    }
    owner.send_signal(signal.SIGTERM)
    owner.wait(timeout=5)
    output = output_path.read_text()
    assert owner.returncode == 1 and "first: cleanup failed" in output
    return env, state_path, identities


def test_partial_cleanup_retry_stops_only_retained_identity_in_recorded_qa_mode(tmp_path):
    env, state_path, identities = _launch_partial(tmp_path)
    first_pid = int(identities["first"]["pid"])
    try:
        retained = json.loads(state_path.read_text())
        assert [row["name"] for row in retained["services"]] == ["first"]
        assert not is_alive(int(identities["second"]["pid"]))
        retry = run_entry(ROOT / "run", env, "down")
        assert retry.returncode == 0 and "first: stopped" in retry.stdout
        assert not state_path.exists() and not is_alive(first_pid)
        assert (tmp_path / "first.stops").read_text() == "2"
        assert (tmp_path / "second.stops").read_text() == "1"
        assert (tmp_path / "first.starts").read_text() == "1"
        assert (tmp_path / "second.starts").read_text() == "1"
        assert (tmp_path / "contexts").read_text().splitlines() == ["qa", "qa"]
    finally:
        if is_alive(first_pid):
            os.kill(first_pid, signal.SIGTERM)
            wait_for(lambda: not is_alive(first_pid))


def test_cleanup_retry_refuses_stale_owned_identity_without_stopping_process(tmp_path):
    env, state_path, identities = _launch_partial(tmp_path)
    first_pid = int(identities["first"]["pid"])
    try:
        retained = json.loads(state_path.read_text())
        retained["services"][0]["identity"]["start"] += " changed"
        state_path.write_text(json.dumps(retained))
        retry = run_entry(ROOT / "run", env, "down")
        assert retry.returncode == 1 and "ownership identity changed" in retry.stderr
        assert is_alive(first_pid)
        assert (tmp_path / "first.stops").read_text() == "1"
        assert (tmp_path / "second.stops").read_text() == "1"
    finally:
        if is_alive(first_pid):
            os.kill(first_pid, signal.SIGTERM)
            wait_for(lambda: not is_alive(first_pid))
