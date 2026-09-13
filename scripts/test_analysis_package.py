"""Artifact-level checks for the private analysis worker distribution."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tomllib
import venv
import zipfile


REPO_ROOT = Path(__file__).parents[1]


def test_wheel_is_self_contained_and_excludes_repository_only_files(tmp_path: Path) -> None:
    wheel_dir = tmp_path / "wheel"
    subprocess.run(
        [sys.executable, "-m", "build", "--wheel", "--no-isolation", "--outdir", wheel_dir],
        cwd=REPO_ROOT,
        check=True,
    )
    wheels = list(wheel_dir.glob("*.whl"))
    assert len(wheels) == 1

    configured = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())["tool"][
        "setuptools"
    ]["py-modules"]
    expected_sources = {
        f"{module.replace('.', '/')}.py" for module in configured
    } | {
        f"{package}/__init__.py" for package in {module.split('.')[0] for module in configured}
    }
    with zipfile.ZipFile(wheels[0]) as wheel:
        sources = {
            name for name in wheel.namelist() if name.endswith(".py")
        }
        inventory = set(wheel.namelist())
    assert sources == expected_sources
    assert not any(
        forbidden in name
        for name in inventory
        for forbidden in ("test_", "docs.local", "profile.yaml", ".env", "supabase/")
    )

    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    install_root = tmp_path / "installed"
    venv.EnvBuilder(with_pip=True).create(install_root)
    python = install_root / "bin" / "python"
    subprocess.run(
        [python, "-m", "pip", "install", wheels[0]],
        cwd=tmp_path,
        env=environment,
        check=True,
    )
    help_result = subprocess.run(
        [install_root / "bin" / "jrc-analysis-worker", "--help"],
        cwd=tmp_path,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    assert "Drain a bounded hosted extraction/scoring backlog" in help_result.stdout

    probe = (
        "import importlib,json;"
        f"names={configured!r};"
        "print(json.dumps([importlib.import_module(n).__file__ for n in names]))"
    )
    imported = json.loads(
        subprocess.run(
            [python, "-I", "-c", probe],
            cwd=tmp_path,
            env=environment,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    )
    site_packages = (install_root / "lib").resolve()
    assert all(Path(path).resolve().is_relative_to(site_packages) for path in imported)
    assert all(not Path(path).resolve().is_relative_to(REPO_ROOT) for path in imported)
