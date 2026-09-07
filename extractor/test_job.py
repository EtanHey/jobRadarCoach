from __future__ import annotations

import json

import pytest

from extractor import job
from scraper.brain_contract import BrainTransportError


RAW_JD = "Senior backend engineer. " + "Build reliable TypeScript services. " * 3
POSTING_IDS = (
    "00000000-0000-0000-0000-000000003e01",
    "00000000-0000-0000-0000-000000003e02",
)


def logs(capsys) -> list[dict[str, object]]:
    return [json.loads(line) for line in capsys.readouterr().out.splitlines()]


class Result:
    def __init__(self, *, one=None, many=None):
        self.one = one
        self.many = many or []

    def fetchone(self):
        return self.one

    def fetchall(self):
        return self.many


class Connection:
    def __init__(self, *, brain="codex"):
        self.brain = brain
        self.extracted: set[str] = set()
        self.queries: list[str] = []

    def execute(self, query, params=()):
        self.queries.append(query)
        if "from public.profile" in query:
            return Result(one=(self.brain,))
        assert "not exists" in query.casefold()
        assert "regexp_replace" in query
        requested = params[2]
        rows = [
            (posting_id, RAW_JD)
            for posting_id in POSTING_IDS
            if posting_id not in self.extracted
            and (requested is None or posting_id in requested)
        ]
        return Result(many=rows[: params[-1]])


def test_batch_is_bounded_and_second_run_skips_extracted_explicit_ids(capsys) -> None:
    connection = Connection()
    calls = []

    def extract(posting, profile, *, timeout_seconds):
        calls.append((posting, profile, timeout_seconds))
        return {"brain": "ollama", "model": "qwen2.5:7b-instruct"}

    def persist(connection, posting_id, raw_jd, result):
        connection.extracted.add(posting_id)
        return "stored"

    first = job.run_batch(
        connection,
        limit=2,
        timeout_seconds=17,
        posting_ids=POSTING_IDS,
        env={"BRAIN": "ollama"},
        extractor=extract,
        persister=persist,
    )
    second = job.run_batch(
        connection,
        limit=2,
        timeout_seconds=17,
        posting_ids=POSTING_IDS,
        env={"BRAIN": "ollama"},
        extractor=extract,
        persister=persist,
    )

    assert (first, second) == (0, 0)
    assert len(calls) == 2
    assert all(call[1:] == ({"runtime.brain": "codex"}, 17) for call in calls)
    assert sum("from public.profile" in query for query in connection.queries) == 2
    assert all(record["provider"] == "ollama" for record in logs(capsys))


@pytest.mark.parametrize(
    ("failure", "expected_type"),
    (("provider", "BrainTransportError"), ("stale", "StaleJD")),
)
def test_provider_and_stale_failures_return_nonzero(capsys, failure, expected_type) -> None:
    connection = Connection(brain="ollama")

    def extract(*_args, **_kwargs):
        if failure == "provider":
            raise BrainTransportError("private failure detail")
        return {"brain": "ollama", "model": "model"}

    def persist(*_args):
        return "stale"

    result = job.run_batch(
        connection,
        limit=1,
        timeout_seconds=10,
        posting_ids=(POSTING_IDS[0],),
        env={},
        extractor=extract,
        persister=persist,
    )
    records = logs(capsys)

    assert result == 1
    assert any(record.get("failure") == expected_type for record in records)
    assert "private failure detail" not in json.dumps(records)
    assert records[-1]["extracted"] == 0
    assert records[-1]["failed"] == 1


def test_optional_provider_is_explicitly_unsupported(capsys) -> None:
    result = job.run_batch(
        Connection(),
        limit=1,
        timeout_seconds=10,
        env={"BRAIN": "claude"},
        extractor=lambda *_args, **_kwargs: pytest.fail("unsupported provider ran"),
    )

    assert result == 1
    assert logs(capsys)[0]["failure"] == "UnsupportedBrainError"



def test_explicit_environment_reaches_real_extractor_adapter(monkeypatch) -> None:
    from scraper.brain import BrainResult

    calls = []
    def brain(request, snapshot, *, env, timeout_seconds):
        calls.append((dict(env), timeout_seconds))
        facts = {field: {"value": None, "evidence_quote": None}
                 for field in ("location", "remote", "seniority", "salary")}
        facts["stack"] = []
        return BrainResult(facts, "ollama", "observed-test", request=request)

    monkeypatch.setattr(job, "run_brain", brain, raising=False)
    assert job.run_batch(Connection(brain="codex"), limit=1, timeout_seconds=17,
                         env={"BRAIN": "ollama"},
                         persister=lambda *_: "stored") == 0
    assert calls == [({"BRAIN": "ollama"}, 17)]
