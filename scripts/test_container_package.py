"""Import the portable runtime from exactly the Dockerfile COPY sources."""

import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import sysconfig


ROOT = Path(__file__).parents[1]


def test_container_sources_import_without_repository(tmp_path):
    app = tmp_path / "app"
    app.mkdir()
    for line in (ROOT / "scraper/Dockerfile").read_text().splitlines():
        if not line.startswith("COPY "):
            continue
        *sources, destination = shlex.split(line)[1:]
        if not destination.startswith("/app/"):
            continue
        target = app / destination.removeprefix("/app/")
        target.mkdir(parents=True, exist_ok=True)
        for source in sources:
            origin = ROOT / source
            if origin.is_dir():
                shutil.copytree(origin, target, dirs_exist_ok=True)
            else:
                shutil.copy2(origin, target / origin.name)
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    probe = (
        "import sys; sys.path[:0] = sys.argv[1:]; "
        "import classifier.core, extractor.core, extractor; "
        "from pathlib import Path; "
        "assert Path(extractor.__file__).is_relative_to(sys.argv[1])"
    )
    result = subprocess.run(
        [sys.executable, "-I", "-S", "-c", probe, str(app), sysconfig.get_path("purelib")],
        cwd=tmp_path, env=env, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
