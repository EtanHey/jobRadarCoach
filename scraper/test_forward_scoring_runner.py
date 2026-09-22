import copy
import os
import ssl

import pytest

from scraper import forward_scoring_runner as runner
from scraper import forward_scoring_runtime as runtime
from scraper.forward_scoring_inputs import assemble_manifest
from scraper.test_annotate import safe_projection
from scraper.test_forward_scoring_inputs import _inputs


@pytest.fixture(autouse=True)
def _offline_only(monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.delenv("JEV_API_KEY", raising=False)
    monkeypatch.setattr(runtime.jev_client, "_api_key", lambda: "offline-test-only")

    def reject_network(*_args, **_kwargs):
        raise AssertionError("network transport is disabled in runner tests")

    monkeypatch.setattr(runtime.jev_client, "_http_transport", reject_network)


def _manifest():
    manifest = assemble_manifest(safe_projection(), *_inputs())
    manifest["execution"] = runtime.execution_metadata()
    return manifest


def _reference(_row):
    return {
        "fit_score": 60,
        "model": "reference-test",
        "scorer_version": "test",
        "latency_seconds": 0.2,
        "cost_per_row_usd": None,
    }


def _jev(_row, _run_dir, _transport):
    return {
        "run": 1,
        "answer": "maybe",
        "confidence": 0.9,
        "model": "jev-test",
        "latency_seconds": 0.1,
        "cost_usd": 0.0001,
    }


def test_execute_requires_exact_freeze_approval_before_any_call(tmp_path, monkeypatch):
    manifest = _manifest()
    calls = []
    monkeypatch.setattr(
        runtime, "score_reference", lambda *_: calls.append("reference")
    )
    monkeypatch.setattr(runtime, "score_jev", lambda *_: calls.append("jev"))

    with pytest.raises(RuntimeError, match="provider execution is held"):
        runner.execute(manifest, tmp_path / "manifest.json", tmp_path / "run")
    monkeypatch.setenv(runner.PROVIDER_GATE, "wrong-freeze")
    with pytest.raises(RuntimeError, match="provider execution is held"):
        runner.execute(manifest, tmp_path / "manifest.json", tmp_path / "run")

    assert calls == []


def test_execute_single_run_is_atomic_resumable_and_restores_environment(
    tmp_path, monkeypatch
):
    manifest = _manifest()
    first = manifest["rows"][0]
    first["reference"] = _reference(first)
    first["jev"].append(_jev(first, tmp_path, None))
    counts = {"reference": 0, "jev": 0}

    def score_reference(row):
        counts["reference"] += 1
        return _reference(row)

    def score_jev(row, run_dir, transport):
        counts["jev"] += 1
        return _jev(row, run_dir, transport)

    monkeypatch.setattr(runtime, "score_reference", score_reference)
    monkeypatch.setattr(runtime, "score_jev", score_jev)
    monkeypatch.setenv(runner.PROVIDER_GATE, manifest["freeze_receipt"]["sha256"])
    monkeypatch.setenv("JEV_DAILY_USD_CAP", "prior-cap")
    monkeypatch.setenv("JEV_SITE_JRC_FORWARD_SCORING", "prior-mode")

    runner.execute(manifest, tmp_path / "manifest.json", tmp_path / "run")

    assert counts == {"reference": 39, "jev": 39}
    assert all("reference" in row and len(row["jev"]) == 1 for row in manifest["rows"])
    assert manifest["run_receipt"]["freeze_sha256"] == runner.freeze_sha(manifest)
    assert os.environ["JEV_DAILY_USD_CAP"] == "prior-cap"
    assert os.environ["JEV_SITE_JRC_FORWARD_SCORING"] == "prior-mode"
    assert runner.load_manifest(tmp_path / "manifest.json") == manifest


def test_tls_preflight_selects_a_valid_ca_without_network():
    ca_bundle = runner.tls_ca_bundle()
    context = ssl.create_default_context(cafile=str(ca_bundle))

    assert ca_bundle.is_file()
    assert context.cert_store_stats()["x509_ca"] > 0


def test_cap_failure_precedes_reference_calls(tmp_path, monkeypatch):
    manifest = _manifest()
    calls = []
    monkeypatch.setenv(runner.PROVIDER_GATE, manifest["freeze_receipt"]["sha256"])
    monkeypatch.setattr(runtime, "score_reference", lambda *_: calls.append(True))
    monkeypatch.setattr(runtime.jev_client, "maximum_call_cost", lambda: 0.02)

    with pytest.raises(RuntimeError, match="cap"):
        runner.execute(manifest, tmp_path / "manifest.json", tmp_path / "run")

    assert calls == []


def test_invalid_explicit_ca_fails_before_reference_calls(tmp_path, monkeypatch):
    manifest = _manifest()
    calls = []
    invalid_ca = tmp_path / "invalid-ca.pem"
    invalid_ca.write_text("not a certificate\n", encoding="utf-8")
    monkeypatch.setenv(runner.PROVIDER_GATE, manifest["freeze_receipt"]["sha256"])
    monkeypatch.setenv("SSL_CERT_FILE", str(invalid_ca))
    monkeypatch.setattr(
        runtime, "score_reference", lambda *_: calls.append("reference")
    )
    monkeypatch.setattr(runtime, "score_jev", lambda *_: calls.append("jev"))

    with pytest.raises(ValueError, match="CA bundle"):
        runner.execute(manifest, tmp_path / "manifest.json", tmp_path / "run")

    assert calls == []


def test_report_contains_hashes_and_only_real_disagreements():
    manifest = _manifest()
    for row in manifest["rows"]:
        row["reference"] = _reference(row)
        row["jev"].append(_jev(row, None, None))
    report = runner.render_final_report(manifest)

    assert f"Freeze SHA-256: `{runner.freeze_sha(manifest)}`" in report
    assert f"Run SHA-256: `{runner.run_sha(manifest)}`" in report
    assert "## Per-row disagreement ledger" in report
    assert "part3:P17" in report
    assert "comment-17" not in report

    mutated = copy.deepcopy(manifest)
    mutated["rows"][0]["reference"]["fit_score"] = 80
    assert runner.run_sha(mutated) != runner.run_sha(manifest)
