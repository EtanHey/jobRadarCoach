import os
from pathlib import Path
import subprocess
import sys

import pytest

from scripts.runtime_verifier_source import read_verifier_source


def test_regular_source_bytes_and_missing_file(tmp_path):
    path = tmp_path / "verifier.py"
    path.write_bytes(b"synthetic source")
    assert read_verifier_source(path) == b"synthetic source"
    path.unlink()
    with pytest.raises(FileNotFoundError):
        read_verifier_source(path)


@pytest.mark.parametrize("module", ["runtime_qa", "runtime_qa_agent", "runtime_room_agent"])
def test_consumer_refuses_fifo_without_waiting_for_writer(tmp_path, module):
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    fifo = scripts / "verify_agent_qa_receipt.py"
    os.mkfifo(fifo)
    call = "assert subject._verifier_integrity(path) is not None"
    if module == "runtime_room_agent":
        call = "assert not subject.RoomAgentService()._default_verify(SimpleNamespace(repo_root=path.parent.parent), path, 'ws://synthetic:7880').healthy"
    code = ("from pathlib import Path; from types import SimpleNamespace; "
            f"import scripts.{module} as subject; path=Path({str(fifo)!r}); " + call)
    subprocess.run([sys.executable, "-c", code], check=True, timeout=2,
                   cwd=Path(__file__).resolve().parents[1], capture_output=True)


@pytest.mark.parametrize("module", ["runtime_qa", "runtime_qa_agent", "runtime_room_agent"])
def test_consumer_executes_hashed_snapshot_when_path_is_replaced(tmp_path, module, monkeypatch):
    import hashlib
    import importlib
    import json
    from types import SimpleNamespace

    subject = importlib.import_module("scripts." + module)
    mode = "normal" if module == "runtime_room_agent" else "qa"
    verified, replaced = tmp_path / "verified", tmp_path / "replaced"
    source = (f"from pathlib import Path; Path({str(verified)!r}).touch()\n"
              f"print({json.dumps({'status':'READY','mode':mode,'worker_id':'AW_snapshot'}, separators=(',', ':'))!r})\n")
    verifier = tmp_path / "scripts/verify_agent_qa_receipt.py"
    verifier.parent.mkdir()
    verifier.write_text(source)
    pin = "VERIFIER_SHA256" if mode == "normal" else "_VERIFIER_SHA256"
    monkeypatch.setattr(subject, pin, hashlib.sha256(source.encode()).hexdigest())

    def run(command, **kwargs):
        verifier.write_text(f"from pathlib import Path; Path({str(replaced)!r}).touch()\n" + source)
        return subprocess.run([sys.executable, *command[1:]], capture_output=True, text=True,
                              timeout=2, check=False)

    context = SimpleNamespace(repo_root=tmp_path, run=run)
    receipt = tmp_path / "receipt.json"
    if mode == "normal":
        assert subject.RoomAgentService()._default_verify(context, receipt, "ws://synthetic").healthy
    elif module == "runtime_qa_agent":
        assert subject.QaAgentService()._verify(context, receipt, "ws://synthetic")[0] == "AW_snapshot"
    else:
        assert subject.QaRuntimeService()._verify(context, verifier, receipt, "ws://synthetic")[0] == "AW_snapshot"
    assert verified.exists()
    assert not replaced.exists()
