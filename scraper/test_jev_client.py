"""Offline contract tests for the temporary Jev client."""

from __future__ import annotations

import json

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


def response() -> dict[str, object]:
    return {
        "model": "jev-test",
        "answers": {
            "requirement": {
                "type": "choice",
                "choice": "hard_requirement",
                "confidence": 0.9,
                "probabilities": {"hard_requirement": 0.95, "waived_or_no_match": 0.05},
            }
        },
        "usage": {"input_tokens": 10, "output_tokens": 4},
    }


def test_shadow_is_default_and_logs_only_state_hash(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("JEV_SITE_JRC_E5", raising=False)
    monkeypatch.setenv("TYPESAFE_API_KEY", "top-secret")
    seen = []
    answers = jev_client.jev(
        "public posting text",
        [question()],
        site="jrc-e5",
        sanitizer=lambda value: value,
        transport=lambda payload, key: seen.append((payload, key)) or response(),
        log_path=tmp_path / "decisions.jsonl",
        usage_path=tmp_path / "usage.jsonl",
    )
    row = json.loads((tmp_path / "decisions.jsonl").read_text())
    assert answers[0].answer == "hard_requirement"
    assert answers[0].acted is False
    assert seen[0][1] == "top-secret"
    assert set(row) == {
        "ts",
        "site",
        "state_hash",
        "question_id",
        "answer",
        "confidence",
        "fallback_answer",
        "acted",
    }
    assert row["state_hash"] == jev_client.hash_state("public posting text")
    assert "public posting text" not in json.dumps(row)


def test_kill_switch_and_cap_return_fallback_without_transport(
    tmp_path, monkeypatch
) -> None:
    calls = []
    monkeypatch.setenv("TYPESAFE_API_KEY", "secret")
    monkeypatch.setenv("JEV_ENABLED", "0")
    kwargs = dict(
        site="jrc-e5",
        sanitizer=lambda value: value,
        transport=lambda *_: calls.append(True),
        log_path=tmp_path / "d.jsonl",
        usage_path=tmp_path / "u.jsonl",
    )
    assert (
        jev_client.jev("state", [question()], **kwargs)[0].answer
        == "waived_or_no_match"
    )
    monkeypatch.setenv("JEV_ENABLED", "1")
    monkeypatch.setenv("JEV_DAILY_USD_CAP", "0")
    assert (
        jev_client.jev("state", [question()], **kwargs)[0].answer
        == "waived_or_no_match"
    )
    assert calls == []


def test_sanitizer_is_required_and_one_item_per_call() -> None:
    with pytest.raises(TypeError):
        jev_client.jev("state", [question()], site="jrc-e5")
    with pytest.raises(ValueError, match="exactly one"):
        jev_client.jev(
            "state",
            [question(), question()],
            site="jrc-e5",
            sanitizer=lambda value: value,
        )


def test_key_never_appears_in_error_or_log(tmp_path, monkeypatch) -> None:
    key = "never-print-this-key"
    monkeypatch.setenv("TYPESAFE_API_KEY", key)
    monkeypatch.setenv("JEV_DAILY_USD_CAP", "1")

    def fail(_payload, api_key):
        raise RuntimeError(f"bad bearer {api_key}")

    with pytest.raises(jev_client.JevError) as caught:
        jev_client.jev(
            "state",
            [question()],
            site="jrc-e5",
            sanitizer=lambda value: value,
            transport=fail,
            log_path=tmp_path / "d.jsonl",
            usage_path=tmp_path / "u.jsonl",
        )
    combined = str(caught.value) + (tmp_path / "d.jsonl").read_text()
    assert key not in combined


def test_vote_most_cautious_uses_three_independent_calls() -> None:
    answers = iter(["waived_or_no_match", "hard_requirement", "waived_or_no_match"])

    def call():
        answer = next(answers)
        return jev_client.JevAnswer("q", "choice", answer, 0.8, {}, False, "fake")

    assert (
        jev_client.vote_most_cautious(call, cautious="hard_requirement").answer
        == "hard_requirement"
    )
