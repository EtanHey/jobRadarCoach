import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

from scripts.runtime_process import Probe, ProcessService, RuntimeContext, process_snapshot


def wait_for(condition, timeout=4):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return
        time.sleep(.03)
    raise AssertionError("condition did not become true")


def test_changed_process_identity_is_never_signaled(tmp_path):
    unrelated = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"], start_new_session=True,
    )
    try:
        identity = process_snapshot(unrelated.pid)
        assert identity is not None
        identity["start"] += " changed"
        service = ProcessService("tiny", ["unused"], lambda _context: Probe(False))
        assert not service.owns(RuntimeContext(Path.cwd(), tmp_path), identity)
        try:
            service.stop(RuntimeContext(Path.cwd(), tmp_path), identity)
        except RuntimeError as error:
            assert "refusing to signal" in str(error)
        else:
            raise AssertionError("changed identity was accepted")
        assert unrelated.poll() is None
    finally:
        unrelated.terminate()
        unrelated.wait(timeout=3)


def test_group_children_are_stopped_after_leader_exits(tmp_path):
    marker = tmp_path / "child.pid"
    code = (
        "import pathlib,subprocess,sys,time; "
        "c=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)']); "
        "pathlib.Path(sys.argv[1]).write_text(str(c.pid)); time.sleep(30)"
    )
    service = ProcessService(
        "tree", [sys.executable, "-c", code, str(marker)],
        lambda _context: Probe(marker.exists()), startup_timeout=2, shutdown_timeout=1,
    )
    context = RuntimeContext(Path.cwd(), tmp_path / "state")
    identity = service.start(context)
    leader = service._children[int(identity["pid"])]
    try:
        wait_for(marker.exists)
        child_pid = int(marker.read_text())
        os.kill(leader.pid, 15)
        leader.wait(timeout=2)
        assert service.owns(context, identity)
        service.stop(context, identity)
        wait_for(lambda: process_snapshot(child_pid) is None)
    finally:
        if service.owns(context, identity):
            service.stop(context, identity)


def test_qa_environment_overrides_stale_values_for_run_and_children(tmp_path, monkeypatch):
    monkeypatch.setenv("VOICE_QA_MODE", "stale")
    command = [sys.executable, "-c", "import os; print(os.environ.get('VOICE_QA_MODE','unset'))"]
    normal = RuntimeContext(Path.cwd(), tmp_path / "normal")
    qa = RuntimeContext(Path.cwd(), tmp_path / "qa", qa_mode=True)
    assert normal.run(command, env={"VOICE_QA_MODE": "1"}).stdout.strip() == "unset"
    assert qa.run(command, env={"VOICE_QA_MODE": "0"}).stdout.strip() == "1"

    for context, expected in ((normal, "unset"), (qa, "1")):
        marker = tmp_path / expected
        child_code = (
            "import os,pathlib,signal,sys,time; "
            "p=pathlib.Path(sys.argv[1]); p.write_text(os.environ.get('VOICE_QA_MODE','unset')); "
            "signal.signal(signal.SIGTERM,lambda *_:sys.exit()); time.sleep(30)"
        )
        service = ProcessService(
            expected, [sys.executable, "-c", child_code, str(marker)],
            lambda _context, path=marker: Probe(path.exists()),
            startup_timeout=2, shutdown_timeout=1, readiness_interval=.03,
        )
        identity = service.start(context)
        try:
            assert marker.read_text() == expected
        finally:
            service.stop(context, identity)


@pytest.mark.parametrize("extra_child", [False, True])
def test_replaced_descendant_command_is_not_signaled(tmp_path, extra_child):
    trigger, marker = tmp_path / "exec-now", tmp_path / "child.pid"
    descendant = (
        "import os,pathlib,sys,time; p=pathlib.Path(sys.argv[1]); "
        "pathlib.Path(sys.argv[2]).write_text(str(os.getpid())); "
        "exec(\"while not p.exists(): time.sleep(.02)\"); "
        "os.execv(sys.executable,[sys.executable,'-c','import time; time.sleep(25)'])"
    )
    leader_code = "import subprocess,sys,time; "
    if extra_child:
        leader_code += "subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)']); "
    leader_code += "subprocess.Popen(sys.argv[1:]); time.sleep(30)"
    service = ProcessService(
        "replace", [sys.executable, "-c", leader_code, sys.executable, "-c", descendant,
                    str(trigger), str(marker)],
        lambda _context: Probe(marker.exists()), startup_timeout=3, shutdown_timeout=1,
    )
    context = RuntimeContext(Path.cwd(), tmp_path / "state")
    identity = service.start(context)
    leader = service._children[int(identity["pid"])]
    child_pid = int(marker.read_text())
    original = process_snapshot(child_pid)
    try:
        trigger.touch()
        wait_for(lambda: (process_snapshot(child_pid) or {}).get("argv") != original["argv"])
        leader.terminate()
        leader.wait(timeout=2)
        assert not service.owns(context, identity)
        try:
            service.stop(context, identity)
        except RuntimeError as error:
            assert "refusing to signal" in str(error)
        else:
            raise AssertionError("replaced descendant command accepted")
        assert process_snapshot(child_pid) is not None
    finally:
        # This test directly spawned the group and retains ownership of both commands.
        try:
            os.killpg(int(identity["pgid"]), 15)
        except ProcessLookupError:
            pass
        leader.wait(timeout=2)
        wait_for(lambda: process_snapshot(child_pid) is None)


def test_permission_denied_group_probe_is_not_reported_stopped(monkeypatch):
    from scripts.runtime_process import _group_exists

    def denied(*_args):
        raise PermissionError("group still exists")

    monkeypatch.setattr(os, "killpg", denied)
    assert _group_exists(123)
