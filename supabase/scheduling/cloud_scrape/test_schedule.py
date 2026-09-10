import json
from pathlib import Path
import re
import subprocess


HERE = Path(__file__).parent
INSTALL = (HERE / "install.sql").read_text(encoding="utf-8")
DISABLE = (HERE / "disable.sql").read_text(encoding="utf-8")
ROLLBACK = (HERE / "rollback.sql").read_text(encoding="utf-8")
WORKFLOW = (HERE.parents[2] / ".github/workflows/cloud-scrape.yml").read_text(
    encoding="utf-8"
)
SETUP = (HERE.parents[2] / "docs/setup.md").read_text(encoding="utf-8")
PIPELINE = (HERE.parents[2] / "docs/cloud-pipeline.md").read_text(encoding="utf-8")
SCHEDULE_README = (HERE / "README.md").read_text(encoding="utf-8")


def test_install_fixes_target_and_keeps_secret_out_of_cron_command() -> None:
    endpoint = (
        "https://api.github.com/repos/EtanHey/jobRadarCoach/actions/workflows/"
        "cloud-scrape.yml/dispatches"
    )
    cron_command = "select scheduler_private.dispatch_cloud_scrape();"

    assert endpoint in INSTALL
    assert "jsonb_build_object('ref', 'master')" in INSTALL
    assert "'0 */6 * * *'" in INSTALL
    assert f"command = '{cron_command}'" in INSTALL
    assert INSTALL.count(f"'{cron_command}'") == 2
    assert "vault.create_secret" not in INSTALL.lower()
    assert "github_pat_" not in INSTALL.lower()
    assert INSTALL.index("matching_secrets <> 1") < INSTALL.index("cron.schedule(")


def test_dispatcher_and_transient_queue_are_private() -> None:
    normalized = " ".join(INSTALL.lower().split())

    assert "security definer set search_path = ''" in normalized
    assert "revoke all on function scheduler_private.dispatch_cloud_scrape()" in normalized
    assert "revoke select on table net.http_request_queue" in normalized
    assert "revoke select on table vault.decrypted_secrets" in normalized
    assert "from public, anon, authenticated, service_role" in normalized


def test_disable_and_rollback_are_bounded_to_named_schedule() -> None:
    assert "job-radar-cloud-scrape" in DISABLE
    assert "cron.alter_job(target_job_id, active := false)" in DISABLE
    assert "cron.unschedule(target_job_id)" in ROLLBACK
    assert "drop function if exists scheduler_private.dispatch_cloud_scrape()" in ROLLBACK
    assert "drop extension" not in ROLLBACK.lower()
    assert "vault." not in ROLLBACK.lower()


def test_target_workflow_runs_four_times_daily_off_the_hour_and_remains_manual() -> None:
    normalized = " ".join(WORKFLOW.split())

    assert "workflow_dispatch:" in WORKFLOW
    assert re.search(
        r'^  schedule:\n    - cron: "17 \*/6 \* \* \*"$',
        WORKFLOW,
        flags=re.MULTILINE,
    )
    assert "group: cloud-scrape" in WORKFLOW
    assert "cancel-in-progress: false" in normalized
    assert "timeout-minutes: 30" in WORKFLOW
    assert "DATABASE_URL: ${{ secrets.DATABASE_URL }}" in WORKFLOW


def test_docs_make_native_schedule_default_and_supabase_dispatch_mutually_exclusive() -> None:
    assert "00:17, 06:17, 12:17, and 18:17 UTC" in " ".join(SETUP.split())
    assert "job_radar_github_actions_token" not in SETUP
    assert (
        "Do not activate this route while the native GitHub schedule is active"
        in " ".join(SCHEDULE_README.split())
    )
    assert "GitHub Actions native schedule" in PIPELINE
    assert "gpt-5.6-luna" in PIPELINE
    assert "gpt-5.6-terra" in PIPELINE


def test_workflow_summary_jq_filter_compiles_and_renders() -> None:
    match = re.search(
        r"jq -r '([^']+)' cloud-scrape-receipt\.json",
        WORKFLOW,
    )
    assert match is not None
    receipt = {
        "status": "success",
        "exit_code": 0,
        "sources": ["linkedin", "comeet"],
        "network_request_skips": 7,
    }

    result = subprocess.run(
        ["jq", "-r", match.group(1)],
        input=json.dumps(receipt),
        capture_output=True,
        check=False,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        "- Status: `success`",
        "- Exit code: `0`",
        "- Sources: `linkedin, comeet`",
        "- Network requests skipped: `7`",
    ]
