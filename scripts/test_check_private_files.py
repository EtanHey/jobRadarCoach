from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

import pytest


GUARD = Path(__file__).with_name("check_private_files.py")


def git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, text=True, capture_output=True
    )


def init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.name", "Guard Test")
    git(repo, "config", "user.email", "guard@example.invalid")
    return repo


def write(repo: Path, relative: str, content: str = "fixture contents") -> Path:
    path = repo / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


def run_guard(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, os.fspath(GUARD), *args],
        cwd=repo,
        text=True,
        capture_output=True,
    )


@pytest.mark.parametrize(
    "private_path",
    [
        "profile.yaml",
        "nested/profile.yaml",
        "docs.local/note.md",
        "nested/docs.local/note.md",
        ".env",
        "nested/.env.production",
        "settings.local.json",
        "nested/auth.json",
    ],
)
def test_rejects_staged_private_paths(tmp_path: Path, private_path: str) -> None:
    repo = init_repo(tmp_path)
    write(repo, private_path, "PRIVATE_MARKER")
    git(repo, "add", "-f", "--", private_path)

    result = run_guard(repo)

    assert result.returncode == 1
    assert private_path in result.stderr
    assert "PRIVATE_MARKER" not in result.stderr


def test_forced_ignored_add_is_rejected(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    write(repo, ".gitignore", ".env\n")
    write(repo, ".env")
    git(repo, "add", ".gitignore")
    git(repo, "add", "-f", ".env")

    assert run_guard(repo).returncode == 1


def test_safe_examples_and_empty_index_pass(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    assert run_guard(repo).returncode == 0

    write(repo, "profile.example.yaml")
    write(repo, "nested/environment.example")
    git(repo, "add", ".")
    assert run_guard(repo).returncode == 0


def test_spaces_and_newlines_are_nul_safe_and_escaped(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    private_path = "space dir/bad\n\x1bname.local.txt"
    write(repo, private_path)
    git(repo, "add", "--", private_path)

    result = run_guard(repo)

    assert result.returncode == 1
    assert "bad\\n\\u001bname.local.txt" in result.stderr
    assert "bad\n\x1bname.local.txt" not in result.stderr


def test_rename_to_private_path_is_rejected(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    write(repo, "safe.json")
    git(repo, "add", "safe.json")
    git(repo, "commit", "-qm", "base")
    git(repo, "mv", "safe.json", "auth.json")

    assert run_guard(repo).returncode == 1


def test_copied_private_target_is_rejected(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    source = write(repo, "safe.json")
    git(repo, "add", "safe.json")
    git(repo, "commit", "-qm", "base")
    write(repo, "nested/auth.json", source.read_text())
    git(repo, "add", "nested/auth.json")

    assert run_guard(repo).returncode == 1


def test_uses_index_not_worktree(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    write(repo, "safe.txt")
    git(repo, "add", "safe.txt")
    write(repo, ".env")
    assert run_guard(repo).returncode == 0

    write(repo, "nested/auth.json")
    git(repo, "add", "nested/auth.json")
    (repo / "nested/auth.json").unlink()
    assert run_guard(repo).returncode == 1


def test_staged_deletion_is_allowed(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    write(repo, "auth.json")
    git(repo, "add", "-f", "auth.json")
    git(repo, "commit", "-qm", "private history fixture")
    git(repo, "rm", "auth.json")

    assert run_guard(repo).returncode == 0


def test_git_failure_is_closed(tmp_path: Path) -> None:
    result = run_guard(tmp_path)

    assert result.returncode != 0
    assert "Git command failed" in result.stderr


def test_all_tracked_scans_without_a_staged_diff(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    write(repo, "safe.txt")
    write(repo, "nested/.env.test")
    git(repo, "add", "-f", ".")
    git(repo, "commit", "-qm", "tracked fixture")

    assert run_guard(repo).returncode == 0
    assert run_guard(repo, "--all-tracked").returncode == 1


@pytest.mark.parametrize("mode", [(), ("--all-tracked",)])
def test_nested_invocation_cannot_hide_private_paths(
    tmp_path: Path, mode: tuple
) -> None:
    repo = init_repo(tmp_path)
    write(repo, "sub/safe.txt")
    write(repo, "docs.local/private.txt")
    git(repo, "add", "-f", ".")
    if mode:
        git(repo, "commit", "-qm", "tracked fixture")
    git(repo, "config", "diff.relative", "true")
    assert run_guard(repo / "sub", *mode).returncode == 1
