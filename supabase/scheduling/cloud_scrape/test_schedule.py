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
    assert (
        "revoke all on function scheduler_private.dispatch_cloud_scrape()" in normalized
    )
    assert "revoke select on table net.http_request_queue" in normalized
    assert "revoke select on table vault.decrypted_secrets" in normalized
    assert "from public, anon, authenticated, service_role" in normalized


def test_disable_and_rollback_are_bounded_to_named_schedule() -> None:
    assert "job-radar-cloud-scrape" in DISABLE
    assert "cron.alter_job(target_job_id, active := false)" in DISABLE
    assert "cron.unschedule(target_job_id)" in ROLLBACK
    assert (
        "drop function if exists scheduler_private.dispatch_cloud_scrape()" in ROLLBACK
    )
    assert "drop extension" not in ROLLBACK.lower()
    assert "vault." not in ROLLBACK.lower()


def test_target_workflow_remains_manual_and_non_overlapping() -> None:
    normalized = " ".join(WORKFLOW.split())

    assert "workflow_dispatch:" in WORKFLOW
    assert "schedule:" not in WORKFLOW
    assert "group: cloud-scrape" in WORKFLOW
    assert "cancel-in-progress: false" in normalized


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
