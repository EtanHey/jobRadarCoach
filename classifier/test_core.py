from __future__ import annotations

import copy
import json
from typing import Callable

import pytest

from classifier import core, projection
from scraper.brain import BrainRequest, BrainResult, BrainTransportError, run_brain
from scraper.test_annotate import safe_projection, structured_annotation
from scraper.test_brain import Response

PRIVATE = "PRIVATE_SENTINEL_DO_NOT_SEND"
DEFAULT_JD = object()


def wire_annotation(*args, **kwargs) -> dict[str, object]:
    response = structured_annotation(*args, **kwargs)
    response["reasons"] = {
        reason["factor"]: reason for reason in response["reasons"]
    }
    return response

def profile_snapshot() -> dict[str, object]:
    projection = safe_projection()
    projection["candidate"]["professional_depth"] = {
        "TypeScript": ["hands-on"],
        "MCP": ["directed-AI", "studied-with-AI"],
    }
    projection["constraints"]["global_never_claims"].append(PRIVATE)
    projection["fit_signals"][0]["ownership"]["exclusions"].append(PRIVATE)
    candidate = projection["candidate"]
    return {
        "contract_version": 1,
        "candidate.positioning": candidate["positioning"],
        "candidate.tenure_years": candidate["tenure_years"],
        "candidate.location": candidate["location"],
        "candidate.fit_terms": candidate["fit_terms"],
        "candidate.open_to.geographies": candidate["open_to"]["geographies"],
        "candidate.open_to.work_modes": candidate["open_to"]["work_modes"],
        "candidate.open_to.relocation": candidate["open_to"]["relocation"],
        "candidate.preferences.product_company": candidate["preferences"]["product_company"],
        "candidate.preferences.experience_gap": candidate["preferences"]["experience_gap"],
        "candidate.professional_depth": candidate["professional_depth"],
        "fit_signals": projection["fit_signals"],
        "constraints.global_never_claims": projection["constraints"]["global_never_claims"],
        "constraints.evidence_scoped_prohibitions": projection["constraints"]["evidence_scoped_prohibitions"],
        "runtime.brain": "ollama",
        "people": [PRIVATE],
        "connectors": {"private": PRIVATE},
    }


def posting(raw_jd: object = DEFAULT_JD) -> dict[str, object]:
    return {
        "id": "11111111-1111-1111-1111-111111111111",
        "title": "Full-stack TypeScript Engineer",
        "company": "Public Example",
        "location": "Tel Aviv",
        "raw_jd": "Build a public TypeScript and React product with Node.js. " * 12
        if raw_jd is DEFAULT_JD
        else raw_jd,
    }


class SequenceBrain:
    def __init__(self, *steps: object) -> None:
        self.steps = list(steps)
        self.calls: list[tuple[BrainRequest, dict[str, object]]] = []

    def __call__(self, request: BrainRequest, snapshot: dict[str, object]) -> BrainResult:
        self.calls.append((request, snapshot))
        step = self.steps.pop(0)
        if isinstance(step, BaseException):
            raise step
        data = step(request) if isinstance(step, Callable) else step
        assert isinstance(data, dict)
        return BrainResult(data, "ollama", "qwen-test", request=request)


def test_emitted_request_is_professional_only_and_returns_provenance() -> None:
    snapshot = profile_snapshot()
    valid = wire_annotation(posting()["id"])
    captured: dict[str, object] = {}
    def runner(request: BrainRequest, passed_snapshot: dict[str, object]) -> BrainResult:
        captured["snapshot"] = passed_snapshot
        captured["schema"] = request.output_schema
        def opener(http_request, **_kwargs):
            captured["body"] = json.loads(http_request.data)
            return Response({"model": "qwen-test", "done": True,
                             "message": {"content": json.dumps(valid)}})
        return run_brain(request, passed_snapshot, env={}, opener=opener)
    history = [{
        "history_id": "22222222-2222-2222-2222-222222222222",
        "company": "Prior Public Company",
        "role": "Frontend Engineer",
        "application_date": "2026-01-15",
        "outcome": "withdrew",
        "private_notes": PRIVATE,
        "posting_id": PRIVATE,
    }]

    result = core.score_posting(snapshot, posting(), history, brain_runner=runner)

    assert result is not None
    assert (result.brain, result.model, result.annotation["fit_score"]) == ("ollama", "qwen-test", 72)
    assert captured["snapshot"] is snapshot
    body = captured["body"]
    prompt = body["messages"][0]["content"]
    assert body["format"] == captured["schema"]
    assert body["format"]["properties"]["reasons"]["type"] == "object"
    assert '"jd_text"' in prompt and '"raw_jd"' not in prompt
    assert "Prior Public Company" in prompt
    assert "previous company" in prompt and "cooldown" in prompt
    assert "not advanced proficiency" in prompt
    assert PRIVATE not in prompt
    assert '"open_to":' not in prompt and '"preferences":' not in prompt
def test_semantic_failure_retries_once_without_score_zero_stub() -> None:
    bad = wire_annotation(posting()["id"], fit_score=85, fit_tier="weak")
    good = wire_annotation(posting()["id"])
    runner = SequenceBrain(bad, good)

    accepted = core.score_posting(profile_snapshot(), posting(), [], brain_runner=runner)

    assert accepted is not None and accepted.annotation["luna_status"] == "ok"
    assert len(runner.calls) == 2

    rejected_runner = SequenceBrain(bad, copy.deepcopy(bad))
    rejected = core.score_posting(profile_snapshot(), posting(), [], brain_runner=rejected_runner)
    assert rejected is None
    assert len(rejected_runner.calls) == 2


def test_provider_failure_stops_without_retry_or_fallback() -> None:
    runner = SequenceBrain(BrainTransportError("provider unavailable"))

    assert core.score_posting(profile_snapshot(), posting(), [], brain_runner=runner) is None
    assert len(runner.calls) == 1


@pytest.mark.parametrize("raw_jd", [None, "", "title only", 42])
def test_missing_or_sparse_raw_jd_never_reaches_brain(raw_jd: object) -> None:
    runner = SequenceBrain(pytest.fail)

    assert core.score_posting(profile_snapshot(), posting(raw_jd), [], brain_runner=runner) is None
    assert runner.calls == []


@pytest.mark.parametrize(
    "history",
    [
        [{}],
        [{"history_id": "id", "company": " "}],
        [{"history_id": str(index), "company": "Public Company"}
         for index in range(projection.MAX_HISTORY_ENTRIES + 1)],
    ],
)
def test_invalid_or_unbounded_history_fails_before_provider(history: list[dict[str, object]]) -> None:
    runner = SequenceBrain(pytest.fail)

    assert core.score_posting(profile_snapshot(), posting(), history, brain_runner=runner) is None
    assert runner.calls == []


def test_missing_db_profile_field_has_no_seed_file_fallback() -> None:
    snapshot = profile_snapshot()
    del snapshot["candidate.positioning"]
    runner = SequenceBrain(pytest.fail)

    assert core.score_posting(snapshot, posting(), [], brain_runner=runner) is None
    assert runner.calls == []


def test_existing_local_claim_guard_rejects_schema_valid_output() -> None:
    invalid = wire_annotation(
        posting()["id"], fit_line=f"Strong fit because {PRIVATE}."
    )
    runner = SequenceBrain(invalid, copy.deepcopy(invalid))

    assert core.score_posting(profile_snapshot(), posting(), [], brain_runner=runner) is None
    assert len(runner.calls) == 2
