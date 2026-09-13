"""Consistency checks for the production LaunchAgent artifacts."""

from __future__ import annotations

import json
from pathlib import Path
import plistlib
import pytest

from scripts import install_analysis_service


REPO_ROOT = Path(__file__).parents[1]
LABEL = "com.jobradarcoach.local-analysis"


def test_installer_prepares_native_artifacts_without_launchctl(
    tmp_path: Path, monkeypatch
) -> None:
    wheel = tmp_path / "jobradarcoach_analysis-0.1.0-py3-none-any.whl"
    wheel.touch()
    database_url_file = tmp_path / "passwordless-database-url"
    database_url_file.write_text("postgresql://operator@db.example/jobradar\n")
    database_url_file.chmod(0o600)
    codex = tmp_path / "codex"
    helper_source = tmp_path / "local_analysis_credentials.swift"
    helper_source.write_text("// reviewed helper\n")
    credential_helper = tmp_path / "jobradarcoach-analysis-credentials"
    credential_helper.write_bytes(b"reviewed-binary")
    for executable in (codex, credential_helper):
        executable.touch()
        executable.chmod(0o755 if executable == credential_helper else 0o700)
    venv_path = tmp_path / "venv"
    commands: list[tuple[list[object], dict[str, object]]] = []

    def create_venv(_self, destination: Path) -> None:
        (Path(destination) / "bin").mkdir(parents=True)
        (Path(destination) / "bin/python").touch()

    def run(command: list[object], *, check: bool, **kwargs) -> None:
        assert check is True
        commands.append((command, kwargs))
        for entry in ("jrc-analysis-supervisor", "jrc-analysis-worker"):
            path = venv_path / "bin" / entry
            path.touch()
            path.chmod(0o700)

    monkeypatch.setattr(install_analysis_service.venv.EnvBuilder, "create", create_venv)
    monkeypatch.setattr(install_analysis_service.subprocess, "run", run)
    monkeypatch.setattr(install_analysis_service.getpass, "getuser", lambda: "operator")

    state_dir = tmp_path / "state"
    state_dir.mkdir()
    maintenance = state_dir / "maintenance.json"
    maintenance.write_text('{"reason":"owner approval maintenance"}\n')
    launch_agents = tmp_path / "LaunchAgents"
    manifest_template = tmp_path / "manifest.example.json"
    manifest_template.write_text(
        json.dumps({"service_id": LABEL, "launchd": {"label": LABEL},
                    "distribution": {}, "paths": {}})
    )
    arguments = [
        "--wheel", str(wheel),
        "--venv", str(venv_path),
        "--database-url-file", str(database_url_file),
        "--codex", str(codex),
        "--credential-helper-source", str(helper_source),
        "--credential-helper", str(credential_helper),
        "--dashboard-origin", "https://jobs.example.com",
        "--source-commit", "a" * 40,
        "--plist-template", str(
            REPO_ROOT / "docs/com.jobradarcoach.local-analysis.plist.example"
        ),
        "--manifest-template", str(
            manifest_template
        ),
        "--state-dir", str(state_dir),
        "--launch-agents-dir", str(launch_agents),
    ]
    database_url_file.write_text("postgresql://operator:secret@db.example/jobradar\n")
    with pytest.raises(ValueError, match="passwordless"):
        install_analysis_service.main(arguments)
    assert commands == []
    database_url_file.write_text(
        "postgresql://operator@db.example/jobradar?sslpassword=secret\n"
    )
    with pytest.raises(ValueError, match="passwordless"):
        install_analysis_service.main(arguments)
    assert commands == []
    database_url_file.write_text("postgresql://operator@db.example/jobradar\n")
    assert install_analysis_service.main(arguments) == 0

    assert len(commands) == 3
    assert all(
        "launchctl" not in str(part)
        for command, _kwargs in commands
        for part in command
    )
    assert all(kwargs["cwd"] == state_dir for _command, kwargs in commands)
    assert all("PYTHONPATH" not in kwargs["env"] for _command, kwargs in commands)
    assert "--force-reinstall" in commands[0][0]
    with (launch_agents / f"{LABEL}.plist").open("rb") as source:
        job = plistlib.load(source)
    assert job["ProgramArguments"] == [str(venv_path / "bin/jrc-analysis-supervisor")]
    environment = job["EnvironmentVariables"]
    assert environment["JRC_LOCAL_ANALYSIS_CREDENTIAL_TIMEOUT_SECONDS"] == "60"
    assert environment["JRC_LOCAL_ANALYSIS_CREDENTIAL_HELPER"] == str(credential_helper)
    assert environment["DATABASE_URL"] == "postgresql://operator@db.example/jobradar"
    assert "JRC_ONEPASSWORD_CLI" not in environment
    assert "JRC_LOCAL_ANALYSIS_ENV_FILE" not in environment
    assert environment["JRC_LOCAL_ANALYSIS_RUN_TIMEOUT_SECONDS"] == "1620"

    manifest_path = state_dir / "service-manifest.json"
    manifest = json.loads(manifest_path.read_text())
    assert "db.example" not in manifest_path.read_text()
    assert manifest["dashboard_origin"] == "https://jobs.example.com"
    assert len(manifest["distribution"]["wheel_sha256"]) == 64
    assert manifest_path.stat().st_mode & 0o777 == 0o600
    assert state_dir.stat().st_mode & 0o777 == 0o700
    assert maintenance.read_text() == '{"reason":"owner approval maintenance"}\n'

    helper_source.write_text("// changed helper\n")
    with pytest.raises(RuntimeError, match="explicitly reprovision"):
        install_analysis_service.main(arguments)
    assert len(commands) == 3
    assert credential_helper.read_bytes() == b"reviewed-binary"
