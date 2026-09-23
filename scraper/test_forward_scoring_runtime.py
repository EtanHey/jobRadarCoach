import copy
import sys
from types import SimpleNamespace

import pytest

from classifier import core, projection
from scraper import forward_scoring_runtime as runtime
from scraper.annotate import provider_payload_projection
from scraper.brain import BrainResult
from scraper.codex_process import verify_codex_version
from scraper.forward_scoring_inputs import assemble_manifest
from scraper.forward_scoring_inputs import _freeze_identity, _sha
from scraper.test_annotate import safe_projection, structured_annotation
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


def test_reference_scoring_uses_full_local_profile_and_frozen_posting(
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
    assert seen["profile"] is frozen["reference_validation_profile"]
    assert seen["posting"] == frozen["hosted_payload"]["public_posting"]
    assert seen["history"] == []
    assert seen["options"]["profile_snapshot"] == frozen["reference_validation_profile"]
    assert (
        seen["options"]["validation_profile"] == frozen["reference_validation_profile"]
    )
    assert result["fit_score"] == 73
    assert result["cost_per_row_usd"] is None


def _fictional_reference_case():
    profile = safe_projection()
    profile["candidate"] = {
        "positioning": "Fictional backend engineer",
        "tenure_years": 5.0,
        "fit_terms": ["backend", "python"],
    }
    profile["fit_signals"] = [
        signal
        for signal in profile["fit_signals"]
        if signal["evidence_id"] in {"example-project", "example-workflow"}
    ]
    profile["constraints"] = {
        "global_never_claims": ["imaginary-skill"],
        "evidence_scoped_prohibitions": {},
    }
    posting = {
        "id": "fictional-posting",
        "title": "Example Backend Engineer",
        "company": "Acme",
        "location": "Example City",
        "jd_text": "Build fictional backend services for an example product.",
    }
    hosted = provider_payload_projection(posting, profile)
    answer = structured_annotation(posting["id"])
    answer.pop("fit_tier")
    answer.pop("recommendation")
    answer["reasons"] = {
        reason["factor"]: {
            **{key: value for key, value in reason.items() if key != "evidence_ids"},
            **(
                {"evidence_ids": reason["evidence_ids"][1:]}
                if reason["factor"] != "employer_type"
                else {}
            ),
        }
        for reason in answer["reasons"]
    }
    answer["fit_line_evidence_ids"] = answer["fit_line_evidence_ids"][1:]
    return {
        "frozen_input": {
            "hosted_payload": hosted,
            "reference_validation_profile": profile,
        }
    }, answer


def test_reference_uses_local_constraints_and_full_profile_request():
    row, answer = _fictional_reference_case()
    frozen = row["frozen_input"]
    hosted = frozen["hosted_payload"]
    calls = []

    def runner(request, snapshot):
        calls.append((request, snapshot))
        return BrainResult(
            copy.deepcopy(answer), "codex", "fictional-model", request=request
        )

    diagnostics = []
    assert (
        runtime.core.score_projected(
            hosted["professional_profile"],
            hosted["public_posting"],
            [],
            profile_snapshot=frozen["reference_validation_profile"],
            brain_runner=runner,
            diagnostic=diagnostics.append,
        )
        is None
    )
    assert diagnostics == ["semantic"]

    assert runtime.score_reference(row, runner)["fit_score"] == 72
    assert len(calls) == 3
    assert all(
        snapshot is frozen["reference_validation_profile"] for _, snapshot in calls
    )
    assert calls[0][0].prompt.encode() != calls[-1][0].prompt.encode()
    assert "Verified scope for example-project." not in calls[0][0].prompt
    assert "Verified scope for example-project." in calls[-1][0].prompt
    assert calls[0][0].output_schema == calls[-1][0].output_schema


def test_reference_rejects_invalid_answer_with_local_constraints():
    row, answer = _fictional_reference_case()
    answer["fit_line"] += " imaginary-skill"
    calls = []

    def runner(request, snapshot):
        calls.append(request)
        return BrainResult(answer, "codex", "fictional-model", request=request)

    with pytest.raises(RuntimeError, match=r"reference scorer failed \(semantic\)"):
        runtime.score_reference(row, runner)
    assert len(calls) == runtime.core.MAX_ATTEMPTS


def _fictional_production_case():
    _, answer = _fictional_reference_case()
    signals = [
        signal
        for signal in safe_projection()["fit_signals"]
        if signal["evidence_id"] in {"example-project", "example-workflow"}
    ]
    snapshot = {
        "contract_version": 1,
        "candidate.positioning": "Fictional backend engineer",
        "candidate.tenure_years": 5.0,
        "candidate.location": "Example City",
        "candidate.fit_terms": ["backend", "python"],
        "candidate.open_to.geographies": ["Example City"],
        "candidate.open_to.work_modes": ["remote"],
        "candidate.open_to.relocation": False,
        "candidate.preferences.product_company": "neutral",
        "candidate.preferences.experience_gap": {},
        "candidate.professional_depth": {},
        "fit_signals": signals,
        "constraints.global_never_claims": ["imaginary-skill"],
        "constraints.evidence_scoped_prohibitions": {},
    }
    posting = {
        "id": "fictional-posting",
        "title": "Example Backend Engineer",
        "company": "Acme",
        "location": "Example City",
        "raw_jd": "Build fictional backend services for an example product. " * 5,
    }
    public_posting = projection.public_posting(posting)
    profile = projection.profile_contract(snapshot)
    hosted = provider_payload_projection(public_posting, profile)
    row = {
        "frozen_input": {
            "hosted_payload": hosted,
            "reference_validation_profile": profile,
        }
    }
    return snapshot, posting, row, answer


def test_reference_prompt_matches_production_and_keeps_verified_scope():
    snapshot, posting, row, answer = _fictional_production_case()
    production_requests = []
    reference_requests = []

    def production_runner(request, _snapshot):
        production_requests.append(request)
        return BrainResult(
            copy.deepcopy(answer), "codex", "fictional-model", request=request
        )

    def reference_runner(request, _snapshot):
        reference_requests.append(request)
        return BrainResult(
            copy.deepcopy(answer), "codex", "fictional-model", request=request
        )

    production = core.score_posting(
        snapshot, posting, [], brain_runner=production_runner
    )
    reference = runtime.score_reference(row, reference_runner)

    assert production is not None and production.annotation["fit_score"] == 72
    assert reference["fit_score"] == 72
    assert len(production_requests) == len(reference_requests) == 1
    assert "Verified scope for example-project." in reference_requests[0].prompt
    assert (
        reference_requests[0].prompt.encode() == production_requests[0].prompt.encode()
    )
    assert reference_requests[0].output_schema == production_requests[0].output_schema
    assert runtime.jev_state(row) == row["frozen_input"]["hosted_payload"]


def test_reference_rejects_mismatched_hosted_profile_before_runner():
    _, _, row, _ = _fictional_production_case()
    row["frozen_input"]["hosted_payload"]["professional_profile"]["fit_signals"][0][
        "verified_scope"
    ] = "Changed fictional scope."
    calls = []

    def runner(*args):
        calls.append(args)
        pytest.fail("runner must not be called for a mismatched hosted profile")

    with pytest.raises(ValueError, match="hosted profile differs"):
        runtime.score_reference(row, runner)
    assert calls == []


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
