import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import uuid

import pytest


LAUNCHER = Path(__file__).with_name("runtime_qa_proxy.mjs")


def wait_for(path, status, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            value = json.loads(path.read_text())
            if value.get("status") == status:
                return value
        except (OSError, json.JSONDecodeError):
            pass
        time.sleep(0.025)
    raise AssertionError(f"marker did not reach {status}")


def fixtures(tmp_path):
    module = tmp_path / "proxy.mjs"
    module.write_text("""
import { existsSync } from 'node:fs';
export async function startQaProxy(options) {
  if (await options.verifyAgent() !== true) throw new Error('fixture gate failed');
  let revoked = false; let mutationAttempts = 0;
  if (process.env.FIXTURE_MUTATE === '1') setTimeout(() => { revoked = true; mutationAttempts = 1; }, 50);
  if (process.env.FIXTURE_MUTATE_TRIGGER) {
    const watcher = setInterval(() => {
      if (existsSync(process.env.FIXTURE_MUTATE_TRIGGER)) {
        clearInterval(watcher); revoked = true; mutationAttempts = 1;
      }
    }, 10);
  }
  return { origin: 'http://127.0.0.1:4567', qaUrl: `http://127.0.0.1:4567/mic?qa=${options.qaSessionId}`,
    receipt: () => ({ rooms: [], revoked, mutationAttempts }), invalidateQa: () => { revoked = true; },
    close: async () => {} };
}
""")
    control = tmp_path / "verifier-status"
    control.write_text("ready")
    verifier = tmp_path / "verifier.py"
    verifier.write_text("""
import json, os, pathlib, sys
mode = pathlib.Path(os.environ['FIXTURE_CONTROL']).read_text().strip()
if sys.argv[1:] != ['--require-mode', 'qa', os.environ['QA_RECEIPT_PATH']]:
    print(json.dumps({'status':'NOT_READY','reason':'arguments_invalid'})); raise SystemExit(1)
if os.environ.get('VOICE_QA_MODE') != '1' or os.environ.get('LIVEKIT_URL') != 'ws://expected:7880':
    print('NOT_READY environment_mismatch fixture', file=sys.stderr); raise SystemExit(1)
if mode == 'ready': print(json.dumps({'worker_id':'AW_fixture','status':'READY','mode':'qa'}, separators=(',', ':')))
else: print(json.dumps({'status':'NOT_READY','reason':'registered_worker_absent'})); raise SystemExit(1)
""")
    return module, verifier, control


def launch(tmp_path, module, verifier, control, extra=None):
    marker = tmp_path / "marker.json"
    extra_environment = extra or {}
    expected_hash = extra_environment.get("QA_EXPECTED_VERIFIER_SHA256")
    if expected_hash is None:
        expected_hash = hashlib.sha256(verifier.read_bytes()).hexdigest()
    environment = {
        **os.environ, "VOICE_QA_MODE": "1", "LIVEKIT_API_KEY": "private-key",
        "LIVEKIT_API_SECRET": "private-secret", "QA_SESSION_ID": str(uuid.uuid4()),
        "QA_EXPECTED_WORKER_ID": "AW_fixture", "QA_VERIFIER_PATH": str(verifier),
        "QA_RECEIPT_PATH": str(tmp_path / "receipt.json"),
        "QA_EXPECTED_LIVEKIT_URL": "ws://expected:7880",
        "QA_RUNTIME_STATE_FILE": str(marker), "QA_PROXY_MODULE": str(module),
        "QA_UPSTREAM": "http://127.0.0.1:3410", "QA_UPSTREAM_ORIGIN": "https://ui.test",
        "QA_PROXY_PORT": "4567", "QA_PUBLIC_LIVEKIT_URL": "wss://voice.test",
        "QA_SUPERVISOR_PID": str(os.getpid()), "QA_VERIFY_INTERVAL_MS": "250",
        "QA_PYTHON": sys.executable, "FIXTURE_CONTROL": str(control),
        "NODE_ENV": "test",
        "QA_EXPECTED_VERIFIER_SHA256": expected_hash,
    }
    environment.update(extra_environment)
    child = subprocess.Popen(
        ("node", str(LAUNCHER)), env=environment, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True,
    )
    return child, marker


def test_periodic_verifier_revokes_without_exposing_credentials(tmp_path):
    module, verifier, control = fixtures(tmp_path)
    child, marker = launch(tmp_path, module, verifier, control)
    try:
        ready = wait_for(marker, "READY")
        assert ready["worker_id"] == "AW_fixture"
        assert "private-key" not in marker.read_text() and "private-secret" not in marker.read_text()
        control.write_text("lost")
        revoked = wait_for(marker, "NOT_READY")
        assert revoked["reason"] == "registered_worker_absent"
        assert revoked["proxy_receipt"]["revoked"] is True
    finally:
        child.terminate()
        child.wait(timeout=5)


def test_exact_verifier_output_is_required_before_proxy_import(tmp_path):
    module, verifier, control = fixtures(tmp_path)
    verifier.write_text("print('{\"status\":\"READY\",\"worker_id\":\"AW_fixture\",\"extra\":true}')\n")
    child, marker = launch(tmp_path, module, verifier, control)
    assert child.wait(timeout=5) != 0
    assert wait_for(marker, "NOT_READY")["reason"] == "verifier_output_invalid"


def test_legacy_v1_ready_does_not_qualify(tmp_path):
    module, verifier, control = fixtures(tmp_path)
    verifier.write_text("print('{\"status\":\"READY\",\"worker_id\":\"AW_fixture\"}')\n")
    child, marker = launch(tmp_path, module, verifier, control)
    assert child.wait(timeout=5) != 0
    assert wait_for(marker, "NOT_READY")["reason"] == "verifier_output_invalid"


def test_normal_mode_ready_never_qualifies_for_qa(tmp_path):
    module, verifier, control = fixtures(tmp_path)
    verifier.write_text(
        "print('{\"worker_id\":\"AW_fixture\",\"mode\":\"normal\",\"status\":\"READY\"}')\n"
    )
    child, marker = launch(tmp_path, module, verifier, control)
    assert child.wait(timeout=5) != 0
    assert wait_for(marker, "NOT_READY")["reason"] == "verifier_output_invalid"


def test_structured_verifier_failure_reason_is_preserved(tmp_path):
    module, verifier, control = fixtures(tmp_path)
    verifier.write_text(
        "import json\n"
        "print(json.dumps({'status':'NOT_READY','reason':'threshold_unknown'}))\n"
        "raise SystemExit(1)\n"
    )
    child, marker = launch(tmp_path, module, verifier, control)
    assert child.wait(timeout=5) != 0
    assert wait_for(marker, "NOT_READY")["reason"] == "threshold_unknown"


def test_changed_verifier_source_fails_closed(tmp_path):
    module, verifier, control = fixtures(tmp_path)
    child, marker = launch(
        tmp_path, module, verifier, control,
        {"QA_EXPECTED_VERIFIER_SHA256": "0" * 64},
    )
    assert child.wait(timeout=5) != 0
    assert wait_for(marker, "NOT_READY")["reason"] == "verifier_source_changed"


def test_verifier_receives_required_qa_mode_arguments(tmp_path):
    module, verifier, control = fixtures(tmp_path)
    argv_file = tmp_path / "argv.json"
    verifier.write_text(
        "import json,os,pathlib,sys\n"
        "pathlib.Path(os.environ['FIXTURE_ARGV']).write_text(json.dumps(sys.argv[1:]))\n"
        "print(json.dumps({'status':'READY','mode':'qa','worker_id':'AW_fixture'}))\n"
    )
    child, marker = launch(
        tmp_path, module, verifier, control, {"FIXTURE_ARGV": str(argv_file)},
    )
    try:
        assert wait_for(marker, "READY")["status"] == "READY"
        assert json.loads(argv_file.read_text()) == [
            "--require-mode", "qa", str(tmp_path / "receipt.json"),
        ]
    finally:
        child.terminate()
        child.wait(timeout=5)


def test_proxy_mutation_revocation_marks_run_not_ready(tmp_path):
    module, verifier, control = fixtures(tmp_path)
    child, marker = launch(tmp_path, module, verifier, control, {"FIXTURE_MUTATE": "1"})
    try:
        assert wait_for(marker, "NOT_READY")["reason"] == "browser_mutation_attempt"
    finally:
        child.terminate()
        child.wait(timeout=5)


def test_pending_success_cannot_erase_mutation_reason(tmp_path):
    module, verifier, control = fixtures(tmp_path)
    counter, pending = tmp_path / "count", tmp_path / "pending"
    completed, trigger = tmp_path / "completed", tmp_path / "mutate"
    verifier.write_text("""
import json, os, pathlib, time
counter = pathlib.Path(os.environ['FIXTURE_COUNT'])
count = int(counter.read_text()) + 1 if counter.exists() else 1
counter.write_text(str(count))
if count >= 3:
    pathlib.Path(os.environ['FIXTURE_PENDING']).touch()
    time.sleep(.75)
    pathlib.Path(os.environ['FIXTURE_COMPLETED']).touch()
print(json.dumps({'status':'READY','mode':'qa','worker_id':'AW_fixture'}, separators=(',', ':')))
""")
    child, marker = launch(tmp_path, module, verifier, control, {
        "FIXTURE_COUNT": str(counter), "FIXTURE_PENDING": str(pending),
        "FIXTURE_COMPLETED": str(completed), "FIXTURE_MUTATE_TRIGGER": str(trigger),
    })
    try:
        deadline = time.monotonic() + 5
        while not pending.exists() and time.monotonic() < deadline:
            time.sleep(0.025)
        assert pending.exists()
        trigger.touch()
        assert wait_for(marker, "NOT_READY")["reason"] == "browser_mutation_attempt"
        first_write = marker.stat().st_mtime_ns
        while not completed.exists() and time.monotonic() < deadline:
            time.sleep(0.025)
        assert completed.exists()
        while marker.stat().st_mtime_ns == first_write and time.monotonic() < deadline:
            time.sleep(0.025)
        assert marker.stat().st_mtime_ns != first_write
        assert json.loads(marker.read_text())["reason"] == "browser_mutation_attempt"
    finally:
        child.terminate()
        child.wait(timeout=5)


def test_missing_proxy_dependency_is_specific_not_ready(tmp_path):
    module, verifier, control = fixtures(tmp_path)
    child, marker = launch(tmp_path, tmp_path / "missing.mjs", verifier, control)
    assert child.wait(timeout=5) != 0
    assert wait_for(marker, "NOT_READY")["reason"] == "proxy_module_unavailable"


def test_proxy_start_preserves_verifier_revocation_reason(tmp_path):
    module, verifier, control = fixtures(tmp_path)
    counter = tmp_path / "verify-count"
    verifier.write_text("""
import json, os, pathlib, sys
counter = pathlib.Path(os.environ['FIXTURE_COUNT'])
count = int(counter.read_text()) + 1 if counter.exists() else 1
counter.write_text(str(count))
if count == 1:
    print(json.dumps({'status':'READY','mode':'qa','worker_id':'AW_fixture'}, separators=(',', ':')))
else:
    print('NOT_READY registered_worker_absent fixture', file=sys.stderr)
    raise SystemExit(1)
""")
    child, marker = launch(
        tmp_path, module, verifier, control, {"FIXTURE_COUNT": str(counter)},
    )
    assert child.wait(timeout=5) != 0
    assert wait_for(marker, "NOT_READY")["reason"] == "registered_worker_absent"


def test_verifier_timeout_kills_owned_child(tmp_path):
    module, verifier, control = fixtures(tmp_path)
    pid_file = tmp_path / "verifier.pid"
    verifier.write_text(
        "import os,pathlib,time\n"
        f"pathlib.Path({str(pid_file)!r}).write_text(str(os.getpid()))\n"
        "time.sleep(30)\n"
    )
    child, marker = launch(
        tmp_path, module, verifier, control, {"QA_VERIFIER_TIMEOUT_MS": "250"},
    )
    assert child.wait(timeout=5) != 0
    assert wait_for(marker, "NOT_READY")["reason"] == "verifier_timeout"
    verifier_pid = int(pid_file.read_text())
    with pytest.raises(ProcessLookupError):
        os.kill(verifier_pid, 0)


def test_signal_during_initial_verifier_reaps_detached_child(tmp_path):
    module, verifier, control = fixtures(tmp_path)
    pid_file = tmp_path / "verifier.pid"
    verifier.write_text(
        "import os,pathlib,time\n"
        f"pathlib.Path({str(pid_file)!r}).write_text(str(os.getpid()))\n"
        "time.sleep(30)\n"
    )
    child, marker = launch(
        tmp_path, module, verifier, control, {"QA_VERIFIER_TIMEOUT_MS": "30000"},
    )
    deadline = time.monotonic() + 5
    while not pid_file.exists() and time.monotonic() < deadline:
        time.sleep(0.025)
    verifier_pid = int(pid_file.read_text())
    child.terminate()
    assert child.wait(timeout=5) == 0
    assert wait_for(marker, "STOPPED")["status"] == "STOPPED"
    with pytest.raises(ProcessLookupError):
        os.kill(verifier_pid, 0)


def test_sighup_during_initial_verifier_reaps_detached_child(tmp_path):
    module, verifier, control = fixtures(tmp_path)
    pid_file = tmp_path / "verifier.pid"
    verifier.write_text(
        "import os,pathlib,time\n"
        f"pathlib.Path({str(pid_file)!r}).write_text(str(os.getpid()))\n"
        "time.sleep(30)\n"
    )
    child, marker = launch(
        tmp_path, module, verifier, control, {"QA_VERIFIER_TIMEOUT_MS": "30000"},
    )
    verifier_pid = None
    try:
        deadline = time.monotonic() + 5
        while not pid_file.exists() and time.monotonic() < deadline:
            time.sleep(0.025)
        verifier_pid = int(pid_file.read_text())
        os.kill(child.pid, signal.SIGHUP)
        assert child.wait(timeout=5) == 0
        assert wait_for(marker, "STOPPED")["status"] == "STOPPED"
        with pytest.raises(ProcessLookupError):
            os.kill(verifier_pid, 0)
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=5)
        if verifier_pid is None and pid_file.exists():
            verifier_pid = int(pid_file.read_text())
        if verifier_pid is not None:
            try:
                os.kill(verifier_pid, 9)
            except ProcessLookupError:
                pass


def test_shutdown_during_verifier_source_read_does_not_spawn(tmp_path):
    module, verifier, control = fixtures(tmp_path)
    verifier.unlink()
    os.mkfifo(verifier)
    child, marker = launch(tmp_path, module, verifier, control, {
        "QA_EXPECTED_VERIFIER_SHA256": "0" * 64,
    })
    try:
        time.sleep(0.1)
        if child.poll() is None:
            child.terminate()
        returncode = child.wait(timeout=2)
        if returncode == 0:
            assert wait_for(marker, "STOPPED")["status"] == "STOPPED"
        else:
            assert wait_for(marker, "NOT_READY")["reason"] == "verifier_source_invalid"
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=5)


def test_completed_verifier_reaps_same_group_descendant(tmp_path):
    module, verifier, control = fixtures(tmp_path)
    pid_file = tmp_path / "descendant.pid"
    verifier.write_text(
        "import json,os,pathlib,subprocess,sys\n"
        "child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)'],"
        "stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)\n"
        f"pathlib.Path({str(pid_file)!r}).write_text(str(child.pid))\n"
        "print(json.dumps({'status':'READY','mode':'qa','worker_id':'AW_fixture'},separators=(',',':')))\n"
    )
    child, marker = launch(tmp_path, module, verifier, control)
    try:
        assert wait_for(marker, "READY")["status"] == "READY"
        descendant_pid = int(pid_file.read_text())
        child.terminate()
        assert child.wait(timeout=5) == 0
        assert wait_for(marker, "STOPPED")["status"] == "STOPPED"
        with pytest.raises(ProcessLookupError):
            os.kill(descendant_pid, 0)
    finally:
        if child.poll() is None:
            child.terminate()
            child.wait(timeout=5)


def test_unconfirmed_verifier_cleanup_fails_closed(tmp_path):
    module, verifier, control = fixtures(tmp_path)
    pid_file, hook = tmp_path / "descendant.pid", tmp_path / "deny-kill.mjs"
    verifier.write_text(
        "import json,pathlib,subprocess,sys\n"
        "child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)'],"
        "stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)\n"
        f"pathlib.Path({str(pid_file)!r}).write_text(str(child.pid))\n"
        "print(json.dumps({'status':'READY','mode':'qa','worker_id':'AW_fixture'},separators=(',',':')))\n"
    )
    hook.write_text(
        "const original=process.kill.bind(process);\n"
        "process.kill=(pid,signal)=>{if(pid<0&&signal==='SIGKILL'){"
        "const error=new Error('fixture denied');error.code='EPERM';throw error;}"
        "return original(pid,signal);};\n"
    )
    child, marker = launch(
        tmp_path, module, verifier, control, {"NODE_OPTIONS": f"--import={hook}"},
    )
    descendant_pid = None
    try:
        assert child.wait(timeout=5) != 0
        descendant_pid = int(pid_file.read_text())
        residual_pgid = os.getpgid(descendant_pid)
        failed = wait_for(marker, "NOT_READY")
        assert failed["reason"] == "verifier_cleanup_failed"
        assert failed["verifier_pgids"] == [residual_pgid]
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=5)
        if descendant_pid is None and pid_file.exists():
            descendant_pid = int(pid_file.read_text())
        if descendant_pid is not None:
            try:
                os.kill(descendant_pid, 9)
            except ProcessLookupError:
                pass


def test_concurrent_gate_calls_run_verifier_serially(tmp_path):
    module, verifier, control = fixtures(tmp_path)
    lock = tmp_path / "verifier.lock"
    verifier.write_text("""
import json, os, pathlib, sys, time
lock = pathlib.Path(os.environ['FIXTURE_LOCK'])
try: fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
except FileExistsError:
    print('NOT_READY verifier_overlap fixture', file=sys.stderr); raise SystemExit(1)
try:
    time.sleep(.1); print(json.dumps({'status':'READY','mode':'qa','worker_id':'AW_fixture'}, separators=(',', ':')))
finally:
    os.close(fd); lock.unlink()
""")
    module.write_text(module.read_text().replace(
        "if (await options.verifyAgent() !== true)",
        "if (!(await Promise.all([options.verifyAgent(), options.verifyAgent()])).every(Boolean))",
    ))
    child, marker = launch(tmp_path, module, verifier, control, {"FIXTURE_LOCK": str(lock)})
    try:
        assert wait_for(marker, "READY")["status"] == "READY"
    finally:
        child.terminate()
        child.wait(timeout=5)
