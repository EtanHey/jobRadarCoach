"""Static consistency checks for production service templates."""

import json
from pathlib import Path
import plistlib


ROOT = Path(__file__).parents[1]
LABEL = "com.jobradarcoach.local-analysis"


def test_launchagent_template_uses_installed_native_runtime() -> None:
    with (ROOT / "docs/com.jobradarcoach.local-analysis.plist.example").open("rb") as source:
        job = plistlib.load(source)
    environment = job["EnvironmentVariables"]

    assert job["Label"] == LABEL
    assert job["ProgramArguments"] == ["/ABSOLUTE/VENV/bin/jrc-analysis-supervisor"]
    assert "WorkingDirectory" not in job
    assert environment["DATABASE_URL"] == "REPLACE_WITH_PASSWORDLESS_POSTGRESQL_URI"
    assert "JRC_ONEPASSWORD_CLI" not in environment
    assert "JRC_LOCAL_ANALYSIS_ENV_FILE" not in environment
    assert job["StandardOutPath"].endswith("/logs/launchd.stdout.log")
    assert job["StandardErrorPath"].endswith("/logs/launchd.stderr.log")


def test_manifest_marks_persistent_explicit_stop_and_helper_identity() -> None:
    manifest = json.loads(
        (ROOT / "docs/analysis-service-manifest.example.json").read_text()
    )

    assert manifest["service_id"] == LABEL == manifest["launchd"]["label"]
    assert manifest["role"] == "persistent-production-dependency"
    assert manifest["credential_helper"]["replacement_policy"] == (
        "explicit-reprovision-required"
    )
    assert manifest["cleanup_policy"] == {
        "service_stop": "explicit-only",
        "remove_state": "never-automatic",
        "preserve_logs_on_repair": True,
    }
    assert "maintenance.json" in manifest["paths"]["maintenance_marker"]
