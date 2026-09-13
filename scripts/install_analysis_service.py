#!/usr/bin/env python3
"""Install the analysis wheel and prepare, but do not load, its LaunchAgent."""

from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import subprocess
from urllib.parse import parse_qsl, urlsplit
import venv


LABEL = "com.jobradarcoach.local-analysis"
FULL_COMMIT = re.compile(r"[0-9a-f]{40}")
WHEEL_NAME = re.compile(r"jobradarcoach_analysis-0\.1\.0-py3-none-any\.whl")


def _absolute(value: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise argparse.ArgumentTypeError("must be an absolute path")
    return path.resolve(strict=False)


def _existing_file(value: str) -> Path:
    path = _absolute(value)
    if not path.is_file():
        raise argparse.ArgumentTypeError("must name an existing file")
    return path.resolve()


def _executable(value: str) -> Path:
    path = _existing_file(value)
    if not os.access(path, os.X_OK):
        raise argparse.ArgumentTypeError("must name an executable file")
    return path


def _stable_credential_helper(value: str) -> Path:
    path = Path(os.path.abspath(Path(value).expanduser()))
    if (
        path.resolve() != path
        or path.is_symlink()
        or not path.is_file()
        or not os.access(path, os.X_OK)
    ):
        raise argparse.ArgumentTypeError(
            "must name an existing, executable, non-symlink file"
        )
    if path.parent.stat().st_mode & 0o777 != 0o700:
        raise argparse.ArgumentTypeError("credential helper directory must have mode 0700")
    if path.stat().st_mode & 0o777 != 0o755:
        raise argparse.ArgumentTypeError("credential helper must have mode 0755")
    return path


def _commit(value: str) -> str:
    if not FULL_COMMIT.fullmatch(value):
        raise argparse.ArgumentTypeError("must be a full lowercase Git commit SHA")
    return value


def _origin(value: str) -> str:
    parsed = urlsplit(value)
    try:
        port = parsed.port
    except ValueError as error:
        raise argparse.ArgumentTypeError("must contain a valid HTTPS port") from error
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or port not in (None, 443)
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
    ):
        raise argparse.ArgumentTypeError("must be an HTTPS origin without a path")
    return value.rstrip("/")


def _passwordless_database_url(path: Path) -> str:
    if path.stat().st_mode & 0o077:
        raise ValueError("database URL file must be accessible only to its owner")
    value = path.read_text(encoding="utf-8").strip()
    if not value or "\n" in value or "\r" in value:
        raise ValueError("database URL file must contain exactly one URI")
    parsed = urlsplit(value)
    query_keys = {key.casefold() for key, _ in parse_qsl(parsed.query, keep_blank_values=True)}
    if (
        parsed.scheme not in ("postgres", "postgresql")
        or not parsed.hostname
        or parsed.password is not None
        or parsed.fragment
        or query_keys & {"password", "sslpassword"}
    ):
        raise ValueError("database URL must be a passwordless PostgreSQL URI")
    return value


def _write(path: Path, content: bytes, mode: int) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_bytes(content)
        temporary.chmod(mode)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def install(args: argparse.Namespace) -> None:
    database_url = _passwordless_database_url(args.database_url_file)
    if not WHEEL_NAME.fullmatch(args.wheel.name):
        raise ValueError("wheel must be the reviewed jobradarcoach-analysis 0.1.0 artifact")
    args.state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    args.state_dir.chmod(0o700)
    logs_dir = args.state_dir / "logs"
    logs_dir.mkdir(exist_ok=True, mode=0o700)
    logs_dir.chmod(0o700)
    args.launch_agents_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    manifest_path = args.state_dir / "service-manifest.json"
    helper = {
        "source_path": str(args.credential_helper_source),
        "source_sha256": _sha256(args.credential_helper_source),
        "binary_path": str(args.credential_helper),
        "binary_sha256": _sha256(args.credential_helper),
        "replacement_policy": "explicit-reprovision-required",
    }
    if manifest_path.exists():
        previous = json.loads(manifest_path.read_text(encoding="utf-8")).get(
            "credential_helper"
        )
        identity_fields = (
            "source_sha256",
            "binary_path",
            "binary_sha256",
            "replacement_policy",
        )
        if not isinstance(previous, dict) or any(
            previous.get(field) != helper[field] for field in identity_fields
        ):
            raise RuntimeError(
                "credential helper identity changed; preserve it or explicitly reprovision"
            )
    if not (args.venv / "bin/python").is_file():
        venv.EnvBuilder(with_pip=True).create(args.venv)
    python = args.venv / "bin/python"
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    subprocess.run(
        [
            python,
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--no-input",
            "--force-reinstall",
            args.wheel,
        ],
        check=True,
        cwd=args.state_dir,
        env=environment,
    )
    subprocess.run(
        [python, "-m", "pip", "check"],
        check=True,
        cwd=args.state_dir,
        env=environment,
    )
    supervisor = args.venv / "bin/jrc-analysis-supervisor"
    worker = args.venv / "bin/jrc-analysis-worker"
    if not supervisor.is_file() or not os.access(supervisor, os.X_OK):
        raise RuntimeError("installed wheel did not provide jrc-analysis-supervisor")
    if not worker.is_file() or not os.access(worker, os.X_OK):
        raise RuntimeError("installed wheel did not provide jrc-analysis-worker")
    subprocess.run(
        [worker, "--help"],
        check=True,
        cwd=args.state_dir,
        env=environment,
        stdout=subprocess.DEVNULL,
    )

    with args.plist_template.open("rb") as source:
        job = plistlib.load(source)
    job["Label"] = LABEL
    job["ProgramArguments"] = [str(supervisor)]
    job.pop("WorkingDirectory", None)
    job["EnvironmentVariables"] = {
        "DATABASE_URL": database_url,
        "JRC_LOCAL_ANALYSIS_STATE_DIR": str(args.state_dir),
        "JRC_LOCAL_ANALYSIS_PYTHON": str(python),
        "JRC_LOCAL_ANALYSIS_CREDENTIAL_HELPER": str(args.credential_helper),
        "JRC_LOCAL_ANALYSIS_CREDENTIAL_TIMEOUT_SECONDS": "60",
        "JRC_LOCAL_ANALYSIS_RUN_TIMEOUT_SECONDS": "1620",
        "CODEX": str(args.codex),
    }
    logs = args.state_dir / "logs"
    job["StandardOutPath"] = str(logs / "launchd.stdout.log")
    job["StandardErrorPath"] = str(logs / "launchd.stderr.log")
    plist_path = args.launch_agents_dir / f"{LABEL}.plist"
    _write(plist_path, plistlib.dumps(job, sort_keys=False), 0o600)

    manifest = json.loads(args.manifest_template.read_text(encoding="utf-8"))
    if (
        manifest.get("service_id") != LABEL
        or manifest.get("launchd", {}).get("label") != LABEL
    ):
        raise ValueError("manifest template does not describe the production service")
    manifest.update(
        {
            "dashboard_origin": args.dashboard_origin,
            "owner_os_user": getpass.getuser(),
            "source_commit": args.source_commit,
        }
    )
    manifest["distribution"]["venv_path"] = str(args.venv)
    manifest["distribution"]["wheel_sha256"] = _sha256(args.wheel)
    manifest["launchd"]["plist_path"] = str(plist_path)
    manifest["paths"].update(
        {
            "state_dir": str(args.state_dir),
            "database_url_reference": str(args.database_url_file),
            "maintenance_marker": str(args.state_dir / "maintenance.json"),
        }
    )
    manifest["credential_helper"] = helper
    _write(
        manifest_path,
        (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode(),
        0o600,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel", required=True, type=_existing_file)
    parser.add_argument("--venv", required=True, type=_absolute)
    parser.add_argument("--database-url-file", required=True, type=_existing_file)
    parser.add_argument("--codex", required=True, type=_executable)
    parser.add_argument("--credential-helper-source", required=True, type=_existing_file)
    parser.add_argument(
        "--credential-helper", required=True, type=_stable_credential_helper
    )
    parser.add_argument("--dashboard-origin", required=True, type=_origin)
    parser.add_argument("--source-commit", required=True, type=_commit)
    parser.add_argument("--plist-template", required=True, type=_existing_file)
    parser.add_argument("--manifest-template", required=True, type=_existing_file)
    parser.add_argument("--state-dir", required=True, type=_absolute)
    parser.add_argument("--launch-agents-dir", required=True, type=_absolute)
    args = parser.parse_args(argv)
    install(args)
    print(f"Prepared {LABEL}; launchd was not loaded or stopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
