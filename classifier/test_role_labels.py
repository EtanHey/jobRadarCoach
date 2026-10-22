"""Role identity belongs to the advertised vacancy, never candidate fit evidence."""

from copy import deepcopy
from contextlib import nullcontext
import json

import pytest

from classifier import core, persistence
from scraper.test_annotate import structured_annotation


@pytest.mark.parametrize("title, expected", [
    ("Senior Full Stack Developer", "fullstack"),
    ("Front-end Engineer", "frontend"),
    ("AI Engineer", "ai"),
    ("Speech Engineer", "voice"),
    ("Senior Backend Developer", None),
    ("Software Engineer", None),
    ("Full-stack AI Engineer", None),
    (None, None),
])
@pytest.mark.parametrize("candidate_work", [
    "Shipped production voice-agent tool calling.",
    "Built frontend interfaces for an AI product.",
    "Owned full-stack features from design through launch.",
])
def test_persisted_role_uses_posting_title_only(monkeypatch, title, expected, candidate_work):
    annotation = structured_annotation("synthetic-role")
    for reason in annotation["reasons"][:2]:
        reason["detail"] = candidate_work
    original = deepcopy(annotation)
    captured = persistence._Inputs(
        {
            "id": "synthetic-role", "title": title,
            "raw_jd": "Build APIs. Work alongside frontend, AI and voice teams.",
            "company": "Voice AI Example",
        },
        {"candidate.positioning": candidate_work}, [], "a" * 64, "b" * 64, "c" * 64,
    )
    monkeypatch.setattr(persistence, "_capture", lambda *_args, **_kwargs: captured)

    class Connection:
        inserted = None

        def transaction(self):
            return nullcontext()

        def execute(self, sql, params=()):
            if sql.startswith("insert into public.posting_scores"):
                self.inserted = params
                return self
            return self

        def fetchone(self):
            return None if self.inserted is None else ("synthetic-role",)

    connection = Connection()
    result = core.ScoringResult(annotation, "synthetic", "synthetic-model")
    assert persistence._store(connection, captured, result) == "stored"
    stored = connection.inserted
    assert json.loads(stored[3]) == {
        "role_type": expected, "seniority_match": "positive",
        "remote_ok": "unknown", "red_flag_count": 0,
    }
    assert stored[1] == original["fit_score"]
    assert json.loads(stored[2]) == original["reasons"]
    assert json.loads(stored[-1]) == original
    assert annotation == original
