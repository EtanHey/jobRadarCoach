import copy
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from scraper import forward_scoring_runtime as runtime
from scraper.brain import BrainResult
from scraper.codex_process import verify_codex_version
from scraper.forward_scoring_inputs import assemble_manifest
from scraper.forward_scoring_inputs import _freeze_identity, _sha
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
    return assemble_manifest(safe_projection(), *_inputs())


def test_execution_metadata_records_the_exact_experiment_deviation():
    assert runtime.execution_metadata() == {
        "codex_cli_version": "codex-cli 0.155.1",
        "production_codex_pin": "codex-cli 0.153.4",
        "reference_model": "gpt-5.6-terra",
        "reference_reasoning_effort": "xhigh",
        "experiment_only_deviation": True,
        "scorer_version": runtime.persistence.SCORER_VERSION,
    }


@pytest.mark.parametrize(
    ("reported_version", "accepted"),
    [
        ("codex-cli 0.155.1", True),
        ("codex-cli 0.154.0", False),
        ("codex-cli 0.153.4", False),
        ("codex-cli 0.155.2", False),
    ],
)
def test_reference_version_is_exact(tmp_path, reported_version, accepted):
    executable = tmp_path / "codex"
    executable.write_text(
        f"#!{sys.executable}\nprint({reported_version!r})\n", encoding="utf-8"
    )
    executable.chmod(0o755)

    def invoke():
        verify_codex_version(
            executable,
            cwd=tmp_path,
            env={},
            timeout=1,
            expected_version=runtime.EXPERIMENT_CODEX_VERSION,
        )

    if accepted:
        invoke()
    else:
        with pytest.raises(RuntimeError, match="unsupported"):
            invoke()


def test_validate_frozen_accepts_only_bound_forty_row_manifest():
    manifest = _manifest()

    assert len(runtime.validate_frozen(manifest)) == 40
    assert manifest["freeze_receipt"]["planned_count"] == 40

    part3 = next(row for row in manifest["rows"] if row["part"] == 3)
    part3["gold"]["comment"] = "changed after freeze"
    with pytest.raises(ValueError, match="freeze receipt"):
        runtime.validate_frozen(manifest)


@pytest.mark.parametrize("label", [pytest.param("missing", id="missing"), None])
def test_validate_frozen_rejects_unparseable_verdict_without_a_label(label):
    manifest = _manifest()
    gold = manifest["rows"][0]["gold"]
    gold["verbatim"] = "not an approved verdict"
    if label != "missing":
        gold["label"] = label
    manifest["freeze_receipt"]["sha256"] = _sha(_freeze_identity(manifest))

    with pytest.raises(
        ValueError, match="gold label does not match the approved parser"
    ):
        runtime.validate_frozen(manifest)


def test_reference_scoring_uses_hosted_projection_and_local_validation_profile(
    monkeypatch,
):
    row = _manifest()["rows"][0]
    seen = {}

    def fake_score(profile, posting, history, **options):
        seen.update(profile=profile, posting=posting, history=history, options=options)
        return SimpleNamespace(annotation={"fit_score": 73}, model="reference-test")

    monkeypatch.setattr(runtime.core, "score_projected", fake_score)
    result = runtime.score_reference(row, lambda *_args: None)

    frozen = row["frozen_input"]
    assert seen["profile"] == frozen["hosted_payload"]["professional_profile"]
    assert seen["posting"] == frozen["hosted_payload"]["public_posting"]
    assert seen["history"] == []
    assert seen["options"]["profile_snapshot"] == frozen["reference_validation_profile"]
    assert (
        seen["options"]["validation_profile"] == frozen["reference_validation_profile"]
    )
    assert result["fit_score"] == 73
    assert result["cost_per_row_usd"] is None


def _captured_reference_row():
    fixture = json.loads(
        (
            Path(__file__).parent / "fixtures/reference_validation_profile.json"
        ).read_text()
    )
    return {"frozen_input": fixture}, fixture["raw_data"]


def test_captured_reference_answer_validates_without_changing_hosted_request():
    row, raw = _captured_reference_row()
    frozen = row["frozen_input"]
    hosted = frozen["hosted_payload"]
    captured = []

    def runner(request, snapshot):
        captured.append((request, snapshot))
        return BrainResult(
            copy.deepcopy(raw), "codex", "configured:gpt-5.6-terra", request=request
        )

    legacy_diagnostics = []
    legacy = runtime.core.score_projected(
        hosted["professional_profile"],
        hosted["public_posting"],
        [],
        profile_snapshot=frozen["reference_validation_profile"],
        brain_runner=runner,
        diagnostic=legacy_diagnostics.append,
    )
    assert legacy is None
    assert legacy_diagnostics == ["semantic"]

    result = runtime.score_reference(row, runner)

    assert result["fit_score"] == 82
    assert len(captured) == 3
    assert all(
        snapshot is frozen["reference_validation_profile"] for _, snapshot in captured
    )
    assert captured[0][0].prompt.encode() == captured[-1][0].prompt.encode()
    assert captured[0][0].output_schema == captured[-1][0].output_schema


def test_captured_reference_answer_still_rejects_invalid_evidence():
    row, raw = _captured_reference_row()
    invalid = copy.deepcopy(raw)
    invalid["fit_line"] += " Kubernetes"
    calls = []

    def runner(request, snapshot):
        calls.append(request)
        return BrainResult(
            invalid, "codex", "configured:gpt-5.6-terra", request=request
        )

    with pytest.raises(RuntimeError, match=r"reference scorer failed \(semantic\)"):
        runtime.score_reference(row, runner)
    assert len(calls) == runtime.core.MAX_ATTEMPTS


def test_jev_scoring_sends_only_the_frozen_hosted_payload(tmp_path, monkeypatch):
    row = _manifest()["rows"][0]
    seen = []
    monkeypatch.setenv("JEV_DAILY_USD_CAP", "0.50")

    def transport(payload, _key):
        seen.append(payload["state"])
        return {
            "model": "jev-test",
            "answers": {
                "pursuit_decision": {
                    "type": "choice",
                    "choice": "maybe",
                    "confidence": 0.8,
                    "probabilities": {"pursue": 0.1, "maybe": 0.8, "no": 0.1},
                }
            },
            "usage": {"input_tokens": 10, "output_tokens": 2},
        }

    result = runtime.score_jev(row, tmp_path, transport)

    assert seen == [row["frozen_input"]["hosted_payload"]]
    assert result["run"] == 1
    assert result["answer"] == "maybe"
    assert result["cost_usd"] > 0
