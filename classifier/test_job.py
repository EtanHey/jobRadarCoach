from __future__ import annotations

import json

import pytest

from classifier import core, job
from scraper.brain_contract import BrainTransportError


POSTING_IDS = (
    "00000000-0000-0000-0000-000000004c01",
    "00000000-0000-0000-0000-000000004c02",
    "00000000-0000-0000-0000-000000004c03",
)


def logs(capsys) -> list[dict[str, object]]:
    return [json.loads(line) for line in capsys.readouterr().out.splitlines()]


class Result:
    def __init__(self, one=None):
        self.one = one

    def fetchone(self):
        return self.one


class Connection:
    def __init__(self, brain="codex"):
        self.brain = brain
        self.scored: set[str] = set()
        self.profile_reads = 0

    def execute(self, query, params=()):
        if "from public.profile" in query:
            self.profile_reads += 1
            return Result((self.brain,))
        assert "from public.posting_scores" in query
        return Result(("ollama", "qwen2.5:7b-instruct"))


def test_batch_intersects_eligibility_bounds_calls_and_skips_second_run(capsys) -> None:
    connection = Connection()
    eligible_limits = []
    brain_calls = []

    def candidates(connection, *, limit, posting_ids):
        eligible_limits.append((limit, posting_ids))
        return [posting_id for posting_id in POSTING_IDS[:2]
                if posting_id not in connection.scored and posting_id in posting_ids][:limit]

    def brain(request, profile, *, env, timeout_seconds):
        brain_calls.append((request, profile, env, timeout_seconds))
        return object()

    def score(connection, posting_id, *, brain_runner):
        brain_runner(object(), {"runtime.brain": "codex", "private": "sentinel"})
        connection.scored.add(posting_id)
        return "stored"

    first = job.run_batch(
        connection,
        limit=3,
        timeout_seconds=17,
        posting_ids=POSTING_IDS,
        env={"BRAIN": "ollama", "PRIVATE_ENV": "sentinel"},
        candidate_lister=candidates,
        scorer=score,
        brain=brain,
    )
    second = job.run_batch(
        connection,
        limit=3,
        timeout_seconds=17,
        posting_ids=POSTING_IDS,
        env={"BRAIN": "ollama", "PRIVATE_ENV": "sentinel"},
        candidate_lister=candidates,
        scorer=score,
        brain=brain,
    )

    assert (first, second) == (0, 0)
    assert eligible_limits == [(3, list(POSTING_IDS)), (3, list(POSTING_IDS))]
    assert len(brain_calls) == 2
    assert all(call[2]["BRAIN"] == "ollama" and call[3] == 17 for call in brain_calls)
    assert all("PRIVATE_ENV" not in call[2] for call in brain_calls)
    assert connection.profile_reads == 2
    records = logs(capsys)
    assert all("private" not in record for record in records)
    summaries = [record for record in records if "scored" in record]
    assert summaries[0]["selected_posting_ids"] == list(POSTING_IDS[:2])
    assert summaries[0]["skipped_posting_ids"] == [POSTING_IDS[2]]
    assert summaries[0]["skipped"] == 1
    assert summaries[1]["selected_posting_ids"] == []
    assert summaries[1]["skipped_posting_ids"] == list(POSTING_IDS)
    assert summaries[1]["skipped"] == len(POSTING_IDS)


def test_oversized_explicit_assignment_does_not_claim_complete_skips(capsys) -> None:
    job.run_batch(
        Connection(), limit=1, timeout_seconds=10, posting_ids=POSTING_IDS,
        env={"BRAIN": "ollama"},
        candidate_lister=lambda *_args, **_kwargs: [POSTING_IDS[0]],
        scorer=lambda *_args, **_kwargs: "stored",
    )

    summary = [record for record in logs(capsys) if "scored" in record][-1]
    assert "selected_posting_ids" not in summary
    assert "skipped_posting_ids" not in summary


@pytest.mark.parametrize(
    ("failure", "expected_type"),
    (("failed", "ScoringFailed"), ("stale", "StaleInputs"),
     ("provider", "BrainTransportError")),
)
def test_failures_return_nonzero_without_raw_detail(capsys, failure, expected_type) -> None:
    connection = Connection()

    def score(*_args, **_kwargs):
        if failure == "provider":
            raise BrainTransportError("private failure detail")
        if failure == "failed":
            assert core.score_posting({}, {}, []) is None
        return failure

    result = job.run_batch(
        connection,
        limit=1,
        timeout_seconds=10,
        env={},
        candidate_lister=lambda *_args, **_kwargs: [POSTING_IDS[0]],
        scorer=score,
    )
    records = logs(capsys)

    assert result == 1
    assert any(record.get("failure") == expected_type for record in records)
    if failure == "failed":
        failed_record = next(record for record in records if record.get("failure") == expected_type)
        assert failed_record["failure_category"] == "projection"
    assert "private failure detail" not in json.dumps(records)
    assert records[-1]["scored"] == 0
    assert records[-1]["failed"] == 1


def test_optional_provider_fails_before_selection_or_model(capsys) -> None:
    result = job.run_batch(
        Connection(),
        limit=1,
        timeout_seconds=10,
        env={"BRAIN": "cursor-agent"},
        candidate_lister=lambda *_args, **_kwargs: pytest.fail("selection ran"),
        brain=lambda *_args, **_kwargs: pytest.fail("provider ran"),
    )

    assert result == 1
    assert logs(capsys)[0]["failure"] == "UnsupportedBrainError"


@pytest.mark.parametrize(
    ("settings", "expected_model"),
    [
        ({"BRAIN": "codex"}, "gpt-5.6-terra"),
        ({"BRAIN": "codex", "CODEX_MODEL": "gpt-5.6-luna"}, "gpt-5.6-luna"),
        ({"BRAIN": "ollama"}, None),
    ],
)
def test_classifier_model_default_preserves_overrides_and_ollama(settings, expected_model):
    calls = []

    def brain(_request, _profile, *, env, timeout_seconds):
        calls.append(dict(env))
        assert timeout_seconds == 120
        return object()

    def score(_connection, _posting_id, *, brain_runner):
        brain_runner(object(), {})
        return "stored"

    assert job.run_batch(
        Connection(), limit=1, timeout_seconds=120, env=settings,
        candidate_lister=lambda *_args, **_kwargs: [POSTING_IDS[0]],
        scorer=score, brain=brain,
    ) == 0
    assert calls[0].get("CODEX_MODEL") == expected_model
