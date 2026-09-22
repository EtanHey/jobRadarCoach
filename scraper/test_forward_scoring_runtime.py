from types import SimpleNamespace

import pytest

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
    return assemble_manifest(safe_projection(), *_inputs())


def test_validate_frozen_accepts_only_bound_forty_row_manifest():
    manifest = _manifest()

    assert len(runtime.validate_frozen(manifest)) == 40
    assert manifest["freeze_receipt"]["planned_count"] == 40

    part3 = next(row for row in manifest["rows"] if row["part"] == 3)
    part3["gold"]["comment"] = "changed after freeze"
    with pytest.raises(ValueError, match="freeze receipt"):
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
    assert result["fit_score"] == 73
    assert result["cost_per_row_usd"] is None


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
