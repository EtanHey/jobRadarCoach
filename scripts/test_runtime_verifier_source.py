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
