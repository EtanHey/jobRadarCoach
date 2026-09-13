from __future__ import annotations

from pathlib import Path
import os
import shutil
import subprocess
import sys

import pytest


SOURCE = Path(__file__).with_name("local_analysis_credentials.swift")
SYNTHETIC_SECRET = "synthetic-password-never-print"


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS Security.framework only")
def test_native_keychain_helper_no_ui_contract(tmp_path: Path) -> None:
    swiftc = shutil.which("swiftc")
    if swiftc is None:
        pytest.skip("swiftc unavailable")
    executable = tmp_path / "credential-self-test"
    compiled = subprocess.run(
        [swiftc, "-D", "TESTING", str(SOURCE), "-o", str(executable)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=60,
        check=False,
    )
    assert compiled.returncode == 0, compiled.stderr
    assert SYNTHETIC_SECRET not in compiled.stdout
    assert SYNTHETIC_SECRET not in compiled.stderr

    test_root = tmp_path / "native-keychains"
    test_root.mkdir(mode=0o700)
    environment = os.environ.copy()
    environment["JRC_CREDENTIAL_TEST_ROOT"] = str(test_root)
    try:
        result = subprocess.run(
            [str(executable)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=15,
            check=False,
            env=environment,
        )
    finally:
        for keychain in test_root.glob(
            "jrc-credential-self-test-*/synthetic.keychain-db"
        ):
            subprocess.run(
                ["/usr/bin/security", "delete-keychain", str(keychain)],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
                check=False,
            )
        shutil.rmtree(test_root, ignore_errors=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == (
        "SELF_TEST_OK synthetic_flow native_success native_missing_no_ui "
        "native_locked_no_ui native_acl_denied_no_ui"
    )
    assert result.stderr == ""
    assert SYNTHETIC_SECRET not in result.stdout
    assert SYNTHETIC_SECRET not in result.stderr


def test_production_source_has_no_test_secret_or_allow_any_acl() -> None:
    source = SOURCE.read_text(encoding="utf-8")
    production_source = source.split("#if TESTING", maxsplit=1)[0]
    assert SYNTHETIC_SECRET not in production_source
    assert 'setenv("PGPASSWORD"' in production_source
    assert "context.interactionNotAllowed = true" in production_source
    assert "kSecUseAuthenticationContext" in production_source
    assert "kSecUseAuthenticationUIFail" in production_source
    assert "kSecAttrAccess as String" in production_source
    assert "-A" not in production_source
    disabled = production_source.index("SecKeychainSetUserInteractionAllowed(false)")
    status = production_source.index("SecKeychainGetStatus")
    lookup = production_source.index("SecItemCopyMatching")
    assert disabled < status < lookup


def test_self_test_unwinds_cleanup_before_top_level_exit() -> None:
    source = SOURCE.read_text(encoding="utf-8")
    self_test = source.split("private func executeSelfTests() throws", maxsplit=1)[1]
    self_test = self_test.split("private func runSelfTests()", maxsplit=1)[0]
    assert "exit(" not in self_test
    assert "defer {\n        SecKeychainDelete(keychain)" in self_test
    assert "defer {\n        _ = SecKeychainSetUserInteractionAllowed" in self_test
    assert "try? FileManager.default.removeItem" in self_test
    assert source.rfind("exit(selfTestExit)") > source.rfind("runSelfTests()")
