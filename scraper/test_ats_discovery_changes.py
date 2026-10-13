"""Weekly eligibility persists miss cooldowns without hit/error date churn."""

from datetime import date
import json
from pathlib import Path
import subprocess
import sys

import pytest

from scraper.ats_discovery import skip_miss
from scraper.ats_discovery_changes import meaningful_cache_change


def record(result, date="2026-09-23", slug="acme"):
    return {"result": result, "last_checked_at": date, "slug_tried": slug}


def test_reviewers_112_tenants_and_twenty_date_bumps_do_not_open_pr():
    previous = {str(n): record("hit" if n < 10 else "error") for n in range(20)}
    current = {key: {**value, "last_checked_at": "2026-10-13"} for key, value in previous.items()}
    assert not meaningful_cache_change(previous, current)


def test_newer_miss_dates_persist_all_1030_renewed_cooldowns():
    previous = {str(n): record("miss") for n in range(1030)}
    renewed = {key: {**row, "last_checked_at": "2026-10-25"} for key, row in previous.items()}
    assert meaningful_cache_change(previous, renewed)
    assert not meaningful_cache_change(previous, previous)
    assert not meaningful_cache_change(renewed, previous)
    assert not skip_miss(previous["0"], date(2026, 11, 1))
    assert skip_miss(renewed["0"], date(2026, 11, 1))


@pytest.mark.parametrize("before,after,expected", [
    ({}, {"new": record("miss")}, True),
    ({}, {"new": record("hit")}, True),
    ({}, {"new": record("error")}, False),
    ({"old": record("hit")}, {"old": record("error")}, False),
    ({"old": record("miss")}, {"old": record("error")}, False),
    ({"old": record("error")}, {"old": record("miss")}, True),
    ({"old": record("miss")}, {"old": record("hit")}, True),
    ({"old": record("hit")}, {"old": record("miss")}, True),
    ({"old": record("hit")}, {"old": record("hit", slug="other")}, False),
    ({"old": record("hit")}, {}, False),
    ({}, {}, False),
])
def test_eligibility(before, after, expected):
    assert meaningful_cache_change(before, after) is expected


def test_cli_compares_against_checked_in_cache(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    path = tmp_path / "scraper/ats-probe-cache.json"
    path.parent.mkdir()
    path.write_text(json.dumps({"old": record("hit")}))
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "-c", "user.name=Test", "-c", "user.email=test@example.test", "commit", "-qm", "fixture"], cwd=tmp_path, check=True)
    root = Path(__file__).resolve().parents[1]
    import os
    env = {**os.environ, "PYTHONPATH": str(root)}
    command = [sys.executable, "-m", "scraper.ats_discovery_changes"]
    path.write_text(json.dumps({"old": record("hit", date="2026-10-13")}))
    assert subprocess.check_output(command, cwd=tmp_path, env=env, text=True).strip() == "false"
    path.write_text(json.dumps({"old": record("hit"), "new": record("miss")}))
    assert subprocess.check_output(command, cwd=tmp_path, env=env, text=True).strip() == "true"


def workflow_run(step):
    root = Path(__file__).resolve().parents[1]
    text = (root / ".github/workflows/ats-discovery-weekly.yml").read_text()
    block = text.split(f"      - name: {step}\n", 1)[1].split("        run: |\n", 1)[1]
    block = block.split("      - name:", 1)[0]
    return "\n".join(line[10:] for line in block.splitlines())


@pytest.mark.parametrize("scenario,creates,exit_code", [
    ("twenty-date-bumps", False, 0),
    ("errors-only", False, 0),
    ("new-miss", True, 0),
    ("renewed-misses", True, 0),
    ("registry", True, 0),
    ("pr-failure", True, 42),
])
def test_actual_pr_step_and_orphan_cleanup(tmp_path, scenario, creates, exit_code):
    import os
    root = Path(__file__).resolve().parents[1]
    repo, remote, commands = (tmp_path / name for name in ("repo", "remote", "bin"))
    subprocess.run(["git", "init", "-qb", "master", str(repo)], check=True)
    subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
    def git(*args):
        return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)
    git("config", "user.name", "Test")
    git("config", "user.email", "test@example.test")
    git("remote", "add", "origin", str(remote))
    (repo / "scraper").mkdir()
    registry = repo / "scraper/source-registry.json"
    registry.write_bytes((root / "scraper/source-registry.json").read_bytes())
    tenants_before = len(json.loads(registry.read_text())["tenants"])
    previous = {str(n): record("hit" if n < 10 else "error") for n in range(20)}
    if scenario == "renewed-misses":
        previous = {str(n): record("miss") for n in range(1030)}
    cache = repo / "scraper/ats-probe-cache.json"
    cache.write_text(json.dumps(previous))
    git("add", ".")
    git("commit", "-qm", "fixture")
    git("push", "-qu", "origin", "master")
    if scenario == "errors-only":
        current = {**{key: record("error", date="2026-10-13") for key in previous}, "new-error": record("error")}
    else:
        current = {key: {**row, "last_checked_at": "2026-10-13"} for key, row in previous.items()}
    if scenario in {"new-miss", "pr-failure"}:
        current["new-miss"] = record("miss")
    cache.write_text(json.dumps(current))
    if scenario == "registry":
        payload = json.loads(registry.read_text())
        payload["tenants"][0]["provenance"].append({"kind": "fixture", "reference": "https://example.test/board"})
        registry.write_text(json.dumps(payload, indent=2) + "\n")
    (repo / "ats-discovery-stats.json").write_text(json.dumps({"registry_before": tenants_before, "registry_after": tenants_before}))
    if scenario == "twenty-date-bumps":
        assert git("diff", "--name-only").stdout.strip() == "scraper/ats-probe-cache.json"
        assert subprocess.run(["git", "diff", "--quiet", "--", "scraper/source-registry.json", "scraper/ats-probe-cache.json"], cwd=repo).returncode == 1
    commands.mkdir()
    gh = commands / "gh"
    gh.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$GH_LOG"\nif [ "$1 $2" = "pr create" ]; then\n if [ "$PR_FAIL" = 1 ]; then exit 42; fi\n echo "https://example.test/pr/1"\nfi\n')
    gh.chmod(0o755)
    env = {**os.environ, "PATH": str(commands) + ":" + str(Path(sys.executable).parent) + ":" + os.environ["PATH"], "PYTHONPATH": str(root), "GITHUB_REPOSITORY": "Test/fixture", "GITHUB_RUN_ID": "123", "GITHUB_STEP_SUMMARY": str(tmp_path / "summary"), "GH_LOG": str(tmp_path / "gh.log"), "PR_FAIL": "1" if scenario == "pr-failure" else "0"}
    result = subprocess.run(["bash", "-c", workflow_run("Validate and open a reviewable PR")], cwd=repo, env=env, capture_output=True, text=True)
    assert result.returncode == exit_code, result.stdout + result.stderr
    calls = (tmp_path / "gh.log").read_text() if (tmp_path / "gh.log").exists() else ""
    assert ("pr create" in calls) is creates
    branch = "data/ats-discovery-weekly-123"
    remote_heads = git("ls-remote", "--heads", "origin", branch).stdout
    if scenario == "pr-failure":
        assert not remote_heads
        assert "::error::Discovery PR creation failed" in result.stdout
        assert "workflow run" not in calls
    elif creates:
        assert remote_heads
        assert f"workflow run ats-discovery-validate.yml --repo Test/fixture --ref {branch}" in calls
        assert f"workflow run python-tests.yml --repo Test/fixture --ref {branch}" in calls
    else:
        assert not remote_heads


@pytest.mark.parametrize("probe_exit,expected", [(0, 0), (124, 0), (137, 137), (2, 2)])
def test_probe_timeout_preserves_partial_cache_and_real_errors_fail(tmp_path, probe_exit, expected):
    import os
    timeout = tmp_path / "timeout"
    timeout.write_text('#!/bin/sh\nprintf "partial cache" > "$CACHE_RECEIPT"\nexit "$PROBE_EXIT"\n')
    timeout.chmod(0o755)
    env = {**os.environ, "PATH": str(tmp_path) + ":" + os.environ["PATH"], "PROBE_EXIT": str(probe_exit), "CACHE_RECEIPT": str(tmp_path / "cache"), "GITHUB_STEP_SUMMARY": str(tmp_path / "summary")}
    result = subprocess.run(["bash", "-c", workflow_run("Probe public ATS boards")], cwd=tmp_path, env=env, capture_output=True, text=True)
    assert result.returncode == expected
    assert (tmp_path / "cache").read_text() == "partial cache"
    if probe_exit == 124:
        assert json.loads((tmp_path / "ats-discovery-stats.json").read_text())["partial"] is True
