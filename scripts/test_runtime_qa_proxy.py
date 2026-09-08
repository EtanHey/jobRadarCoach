import json
import os
from pathlib import Path
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
if os.environ.get('VOICE_QA_MODE') != '1' or os.environ.get('LIVEKIT_URL') != 'ws://expected:7880':
    print('NOT_READY environment_mismatch fixture', file=sys.stderr); raise SystemExit(1)
if mode == 'ready': print(json.dumps({'status':'READY','worker_id':'AW_fixture'}, separators=(',', ':')))
else: print('NOT_READY registered_worker_absent fixture', file=sys.stderr); raise SystemExit(1)
""")
    return module, verifier, control


def launch(tmp_path, module, verifier, control, extra=None):
    marker = tmp_path / "marker.json"
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
    }
    environment.update(extra or {})
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
print(json.dumps({'status':'READY','worker_id':'AW_fixture'}, separators=(',', ':')))
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
    print(json.dumps({'status':'READY','worker_id':'AW_fixture'}, separators=(',', ':')))
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
    time.sleep(.1); print(json.dumps({'status':'READY','worker_id':'AW_fixture'}, separators=(',', ':')))
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
