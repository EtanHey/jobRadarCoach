"""Offline contract tests for the temporary Jev client."""

from __future__ import annotations

import json
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor

import pytest

from scraper import jev_client

def question(fallback: str = "waived_or_no_match") -> jev_client.Question:
    return jev_client.Question(
        id="requirement",
        type="choice",
        instructions="Classify this posting.",
        criteria={"hard_requirement": "Required", "waived_or_no_match": "Not required"},
        fallback=fallback,
    )
def response(*, input_tokens: int = 10, output_tokens: int = 4) -> dict[str, object]:
    return {
        "model": "jev-test",
        "answers": {"requirement": {"type": "choice", "choice": "hard_requirement", "confidence": 0.9,
                                      "probabilities": {"hard_requirement": 0.95, "waived_or_no_match": 0.05}}},
        "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens},
    }
def call(tmp_path, monkeypatch, *, transport, usage="usage.jsonl"):
    monkeypatch.setenv("TYPESAFE_API_KEY", "top-secret")
    return jev_client.jev("public posting text", [question()], site="jrc-e5", sanitizer=lambda value: value,
                          transport=transport, log_path=tmp_path / "decisions.jsonl", usage_path=tmp_path / usage)
def test_shadow_is_default_and_logs_only_state_hash(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("JEV_SITE_JRC_E5", raising=False)
    seen = []
    answers = call(tmp_path, monkeypatch, transport=lambda payload, key: seen.append((payload, key)) or response())
    row = json.loads((tmp_path / "decisions.jsonl").read_text())
    assert answers[0].answer == "hard_requirement"
    assert answers[0].acted is False
    assert seen[0][1] == "top-secret"
    assert set(row) == {"ts", "site", "state_hash", "question_id", "answer", "confidence", "fallback_answer", "acted"}
    assert row["state_hash"] == jev_client.hash_state("public posting text")
    assert "public posting text" not in json.dumps(row)
def test_kill_switch_and_cap_return_fallback_without_transport(tmp_path, monkeypatch) -> None:
    calls = []
    monkeypatch.setenv("JEV_ENABLED", "0")
    assert call(tmp_path, monkeypatch, transport=lambda *_: calls.append(True))[0].fallback_used
    monkeypatch.setenv("JEV_ENABLED", "1")
    monkeypatch.setenv("JEV_DAILY_USD_CAP", "0")
    assert call(tmp_path, monkeypatch, transport=lambda *_: calls.append(True), usage="u2.jsonl")[0].fallback_used
    assert calls == []

@pytest.mark.parametrize("stale_rate", ["0", "0.041"])
def test_price_override_below_model_floor_never_invokes_transport(tmp_path, monkeypatch, stale_rate) -> None:
    calls = []
    monkeypatch.setenv("JEV_DAILY_USD_CAP", "0")
    monkeypatch.setenv("JEV_USD_PER_MTOK", stale_rate)
    with pytest.raises(jev_client.JevError, match="price"):
        call(tmp_path, monkeypatch, transport=lambda *_: calls.append(True) or response())
    assert calls == []
def test_sequential_underestimates_cannot_exceed_cap(tmp_path, monkeypatch) -> None:
    reserve = jev_client.maximum_call_cost()
    one_token_cost = jev_client.DEFAULT_USD_PER_MTOK / 1_000_000
    monkeypatch.setenv("JEV_DAILY_USD_CAP", str(reserve + 1.5 * one_token_cost))
    calls = []
    first = call(tmp_path, monkeypatch, transport=lambda *_: calls.append(True) or response(input_tokens=1))[0]
    second = call(tmp_path, monkeypatch, transport=lambda *_: calls.append(True) or response(input_tokens=1))[0]
    assert first.called and second.called  # reconciliation releases unused reservation
    third = call(tmp_path, monkeypatch, transport=lambda *_: calls.append(True) or response(input_tokens=1))[0]
    assert third.fallback_used and len(calls) == 2
def test_huge_usage_response_is_rejected_and_reservation_stays_charged(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("JEV_DAILY_USD_CAP", str(jev_client.maximum_call_cost()))
    assert call(tmp_path, monkeypatch, transport=lambda *_: response(input_tokens=10_000_000))[0].fallback_used
    calls = []
    assert call(tmp_path, monkeypatch, transport=lambda *_: calls.append(True) or response())[0].fallback_used
    assert calls == []
def test_concurrent_calls_reserve_atomically(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("JEV_DAILY_USD_CAP", str(jev_client.maximum_call_cost()))
    calls = []

    def invoke(_index):
        return call(tmp_path, monkeypatch, transport=lambda *_: calls.append(True) or response(input_tokens=64_000))[0]

    with ThreadPoolExecutor(max_workers=8) as pool:
        answers = list(pool.map(invoke, range(8)))
    assert len(calls) == 1
    assert sum(answer.called for answer in answers) == 1
    assert sum(answer.fallback_used for answer in answers) == 7

@pytest.mark.parametrize(
    "mutate",
    [
        lambda row: row["answers"]["requirement"].update(choice="unknown"),
        lambda row: row["answers"]["requirement"].update(confidence=1.1),
        lambda row: row["answers"]["requirement"].pop("confidence"),
        lambda row: row.update(usage={"input_tokens": -1, "output_tokens": 4}),
        lambda row: row.update(usage={"input_tokens": 1.5, "output_tokens": 4}),
        lambda row: row["answers"]["requirement"].update(probabilities={"hard_requirement": 1.0}),
    ],
)
def test_invalid_upstream_data_logs_and_returns_fallback(tmp_path, monkeypatch, mutate) -> None:
    row = response()
    mutate(row)
    assert call(tmp_path, monkeypatch, transport=lambda *_: row)[0].fallback_used
    logged = json.loads((tmp_path / "decisions.jsonl").read_text())
    assert logged["answer"] == "waived_or_no_match"
    assert logged["acted"] is False

@pytest.mark.parametrize(
    "mutate",
    [
        lambda row: row["answers"]["requirement"].update(confidence="0.9"),
        lambda row: row["answers"]["requirement"]["probabilities"].update(hard_requirement="0.95"),
    ],
)
def test_choice_rejects_numeric_strings(tmp_path, monkeypatch, mutate) -> None:
    row = response()
    mutate(row)
    assert call(tmp_path, monkeypatch, transport=lambda *_: row)[0].fallback_used

def test_sanitizer_is_required_and_one_item_per_call() -> None:
    with pytest.raises(TypeError):
        jev_client.jev("state", [question()], site="jrc-e5")
    with pytest.raises(ValueError, match="exactly one"):
        jev_client.jev("state", [question(), question()], site="jrc-e5", sanitizer=lambda value: value)

def test_noul_and_score_per_type_invariants() -> None:
    usage = {"input_tokens": 10, "output_tokens": 4}
    noul = jev_client.Question("n", "noul", "True?", None, 0.0)
    assert jev_client._parse_response(
        {"model": "test", "answers": {"n": {"type": "noul", "noul": 0.8}}, "usage": usage}, noul
    )[0] == 0.8
    score = jev_client.Question("s", "score", "Rate", ["low", "high"], 0.0)
    valid = {"model": "test", "answers": {"s": {"type": "score", "score": 0.75, "confidence": 0.5,
             "legend": {"0": "low", "1": "high"}, "probabilities": {"0": 0.25, "1": 0.75}}}, "usage": usage}
    assert jev_client._parse_response(valid, score)[0] == 0.75
    valid["answers"]["s"].pop("legend")
    with pytest.raises((KeyError, ValueError)):
        jev_client._parse_response(valid, score)

@pytest.mark.parametrize(
    ("question", "raw", "field"),
    [
        (
            jev_client.Question("n", "noul", "True?", None, 0.0),
            {"model": "test", "answers": {"n": {"type": "noul", "noul": "0.8"}},
             "usage": {"input_tokens": 10, "output_tokens": 4}},
            "noul",
        ),
        (
            jev_client.Question("s", "score", "Rate", ["low", "high"], 0.0),
            {"model": "test", "answers": {"s": {"type": "score", "score": "0.75", "confidence": 0.5,
             "legend": {"0": "low", "1": "high"}, "probabilities": {"0": 0.25, "1": 0.75}}},
             "usage": {"input_tokens": 10, "output_tokens": 4}},
            "score",
        ),
        (
            jev_client.Question("s", "score", "Rate", ["low", "high"], 0.0),
            {"model": "test", "answers": {"s": {"type": "score", "score": 0.75, "confidence": "0.5",
             "legend": {"0": "low", "1": "high"}, "probabilities": {"0": 0.25, "1": 0.75}}},
             "usage": {"input_tokens": 10, "output_tokens": 4}},
            "confidence",
        ),
        (
            jev_client.Question("s", "score", "Rate", ["low", "high"], 0.0),
            {"model": "test", "answers": {"s": {"type": "score", "score": 0.75, "confidence": 0.5,
             "legend": {"0": "low", "1": "high"}, "probabilities": {"0": "0.25", "1": 0.75}}},
             "usage": {"input_tokens": 10, "output_tokens": 4}},
            "probability",
        ),
    ],
)
def test_noul_and_score_reject_numeric_strings(question, raw, field) -> None:
    with pytest.raises((TypeError, ValueError), match=field):
        jev_client._parse_response(deepcopy(raw), question)

def test_api_key_resolution_is_shared_by_custom_and_default_transports(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.setenv("JEV_API_KEY", "jev-fallback-secret")
    seen = []
    jev_client.jev("state", [question()], site="jrc-e5", sanitizer=lambda value: value,
                   transport=lambda _payload, key: seen.append(("custom", key)) or response(),
                   log_path=tmp_path / "custom.jsonl", usage_path=tmp_path / "custom-usage.jsonl")

    monkeypatch.delenv("JEV_API_KEY")
    monkeypatch.setenv("HOME", str(tmp_path))
    key_file = tmp_path / ".config" / "typesafe" / "api-key"
    key_file.parent.mkdir(parents=True)
    key_file.write_text("file-fallback-secret\n", encoding="utf-8")
    monkeypatch.setattr(jev_client, "_http_transport",
                        lambda _payload, key: seen.append(("default", key)) or response())
    jev_client.jev("state", [question()], site="jrc-e5", sanitizer=lambda value: value,
                   log_path=tmp_path / "default.jsonl", usage_path=tmp_path / "default-usage.jsonl")

    assert seen == [("custom", "jev-fallback-secret"), ("default", "file-fallback-secret")]
    logs = (tmp_path / "custom.jsonl").read_text() + (tmp_path / "default.jsonl").read_text()
    assert "fallback-secret" not in logs

def test_invalid_answer_after_invocation_reconciles_known_usage(tmp_path, monkeypatch) -> None:
    row = response(input_tokens=10)
    row["answers"]["requirement"]["confidence"] = "0.9"
    reserve = jev_client.maximum_call_cost()
    actual = 10 * jev_client.DEFAULT_USD_PER_MTOK / 1_000_000
    monkeypatch.setenv("JEV_DAILY_USD_CAP", str(reserve + actual))

    invalid = call(tmp_path, monkeypatch, transport=lambda *_: row)[0]
    valid = call(tmp_path, monkeypatch, transport=lambda *_: response(input_tokens=10))[0]

    assert invalid.fallback_used and invalid.called
    assert invalid.input_tokens == 10
    assert invalid.output_tokens == 4
    assert invalid.cost_usd == actual
    assert valid.called  # invalid answer released its unused conservative reservation

def test_key_never_appears_in_error_or_log(tmp_path, monkeypatch) -> None:
    key = "never-print-this-key"
    monkeypatch.setenv("TYPESAFE_API_KEY", key)
    answer = call(tmp_path, monkeypatch, transport=lambda _payload, api_key: (_ for _ in ()).throw(RuntimeError(api_key)))[0]
    assert answer.fallback_used
    assert key not in (tmp_path / "decisions.jsonl").read_text()

def test_vote_most_cautious_uses_three_independent_calls() -> None:
    answers = iter(["waived_or_no_match", "hard_requirement", "waived_or_no_match"])
    def one():
        return jev_client.JevAnswer("q", "choice", next(answers), 0.8, {}, False, "fake")
    assert jev_client.vote_most_cautious(one, cautious="hard_requirement").answer == "hard_requirement"
