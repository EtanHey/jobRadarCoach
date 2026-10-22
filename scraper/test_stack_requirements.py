"""Synthetic required/optional stack regression cases; no provider or DB calls."""

import copy

import pytest

from classifier import core
from classifier.test_core import SequenceBrain, posting, profile_snapshot, wire_annotation
from scraper.annotate import annotate
from scraper.test_annotate import SequenceRunner, safe_projection, structured_annotation


def score(jd, *, depth=None, human=None):
    snapshot = profile_snapshot()
    if depth is not None:
        snapshot["candidate.professional_depth"] = depth
    row = posting(jd + "\n\nPublic product description. " * 12)
    if human:
        row["human_verdict"] = human
    runner = SequenceBrain(wire_annotation(row["id"]))
    result = core.score_posting(snapshot, row, [], brain_runner=runner)
    assert result is not None
    assert len(runner.calls) == 1
    return result.annotation


def stack_reason(annotation):
    return next(r for r in annotation["reasons"] if r["factor"] == "stack_domain_evidence")


@pytest.mark.parametrize("jd, language", [
    ("**Responsibilities**\n- Design and maintain backend services using C#.", "C#"),
    ("Requirements:\n- Strong proficiency in Java.\nNice To Have\n- TypeScript and React.", "Java"),
    ("## Required Qualifications\n- Experience with C# and TypeScript.", "C#"),
    ("C# is required.", "C#"),
    ("Requirements\n- Experience in Java or Kotlin.", "Java or Kotlin"),
])
def test_missing_required_language_holds_actionable_recommendation(jd, language):
    result = score(jd)
    assert result["recommendation"] == "review"
    assert result["fit_score"] == 72  # No invented numeric penalty.
    reason = stack_reason(result)
    assert reason["assessment"] == "mixed"
    assert language in reason["detail"] and "not evidenced" in reason["detail"]
    assert result["fit_line"].startswith("Check required stack:")


@pytest.mark.parametrize("jd", [
    "Requirements\n- TypeScript experience.\nNice To Have\n- Java and C#.",
    "Qualifications\n- Experience in Java, C#, TypeScript – an advantage.",
    "Requirements\n- Experience in Java or TypeScript.",
    "Requirements\n- Experience in Java/TypeScript.",
    "Requirements\n- Experience in Java OR TypeScript.",
    "Requirements\n- Experience in Java and/or TypeScript.",
    "Requirements\n- Experience in Java, Kotlin, or TypeScript.",
    "Requirements\n- Experience with Java is not required.",
    "Requirements\n- No prior Java experience required.",
    "Requirements\n- C# is a plus.\n- TypeScript experience.",
    "About us\nOur product uses Java.\nRequirements\n- TypeScript experience.",
    "Requirements\n- TypeScript experience.\n**Benefits**\n- Java training.",
    "Requirements\n- Experience in Java or an equivalent language.",
    "Requirements\n- Experience migrating from Java to TypeScript.",
    "Requirements\n- Experience with Java and TypeScript or Kotlin.",
    "Requirements\n- Experience in React Native or TypeScript.",
    "Requirements\n- TypeScript experience.\n## Training\nJava experience.",
    "Requirements\n- TypeScript experience.\nNice To Have\n- Java is required for optional tooling.",
    "Qualifications\n- Experience in Scala, Java, Kotlin, TypeScript/JavaScript (React and Node.js) – an advantage.",
    "Requirements\n- Experience in any language.\nNice To Have\n- Java and C# experience.",
])
def test_optional_alternative_and_nonrequirement_mentions_do_not_penalize(jd):
    assert score(jd)["recommendation"] == "apply"


@pytest.mark.parametrize("modes, expected", [
    (["hands-on"], "apply"),
    (["directed-AI"], "review"),
    (["studied-with-AI"], "review"),
])
def test_candidate_depth_requires_hands_on_evidence(modes, expected):
    result = score("Requirements\n- Java experience.", depth={"Java": modes})
    assert result["recommendation"] == expected


@pytest.mark.parametrize("human", ["apply", "referral", "skip"])
def test_human_verdict_remains_authoritative(human):
    result = score("Requirements\n- Java experience.", human=human)
    assert result["recommendation"] == human
    assert "Java" in stack_reason(result)["detail"]
    assert "not evidenced" in stack_reason(result)["detail"]


def test_preferences_do_not_prove_skill():
    snapshot = profile_snapshot()
    snapshot["candidate.stacks"] = ["Java"]
    snapshot["candidate.fit_terms"] = ["Java"]
    row = posting("Requirements\n- Java experience.\n\n" + "Public product description. " * 12)
    result = core.score_posting(snapshot, row, [], brain_runner=SequenceBrain(wire_annotation(row["id"])))
    assert result.annotation["recommendation"] == "review"


def test_legacy_annotator_has_same_guard_and_does_not_mutate_provider_response():
    row = {"id": "synthetic-stack", "jd_text": "Requirements\n- C# experience."}
    response = structured_annotation(row["id"], recommendation="referral")
    original = copy.deepcopy(response)
    result = annotate(row, profile=safe_projection(),
                      runner=SequenceRunner({"status": "ok", "data": response}))
    assert result["recommendation"] == "review"
    assert "C#" in stack_reason(result)["detail"]
    assert response == original


def test_offline_replay_reports_every_changed_row_and_preserves_input(tmp_path):
    import json
    from scripts.stack_gap_dryrun import report

    annotation = structured_annotation("synthetic-stack")
    rows = [{"id": "required", "company": "Synthetic A", "raw_jd": "Requirements\nJava experience.",
             "posting_scores": {"score_payload": annotation}},
            {"id": "optional", "company": "Synthetic B", "raw_jd": "Nice To Have\nJava experience.",
             "posting_scores": {"score_payload": annotation}},
            {"id": "unscored", "company": "Synthetic C", "posting_scores": None}]
    snapshot = tmp_path / "snapshot.jsonl"
    frozen = "\n".join(json.dumps(row) for row in rows)
    snapshot.write_text(frozen)
    output = report(snapshot, safe_projection())
    counts, changes = [json.loads(block.split("```", 1)[0]) for block in output.split("```json\n")[1:]]
    assert counts == {"before": {"apply": 2, "unscored": 1},
                      "after": {"apply": 1, "review": 1, "unscored": 1}}
    assert [row["id"] for row in changes] == ["required"]
    assert changes[0]["changes"]["recommendation"] == {"before": "apply", "after": "review"}
    assert snapshot.read_text() == frozen


def test_existing_skip_is_not_promoted():
    row = {"id": "synthetic-stack", "jd_text": "Requirements\n- Java experience."}
    result = annotate(row, profile=safe_projection(), runner=SequenceRunner({
        "status": "ok", "data": structured_annotation(row["id"], recommendation="skip"),
    }))
    assert result["recommendation"] == "skip"


def test_verified_tags_cover_requirement_and_guard_is_idempotent():
    from scraper.stack_requirements import apply_stack_gap_guard

    profile = safe_projection()
    profile["fit_signals"][0]["tags"].append("Java")
    annotation = structured_annotation("synthetic-stack")
    row = {"jd_text": "Requirements\n- Java experience."}
    assert apply_stack_gap_guard(annotation, row, profile) == annotation
    profile["fit_signals"][0]["tags"].remove("Java")
    once = apply_stack_gap_guard(annotation, row, profile)
    assert apply_stack_gap_guard(once, row, profile) == once
    assert annotation["recommendation"] == "apply"


def test_javascript_is_not_evidence_of_java_and_weak_prefix_is_preserved():
    from scraper.stack_requirements import apply_stack_gap_guard

    profile = safe_projection()
    profile["fit_signals"][0]["tags"].append("JavaScript")
    annotation = structured_annotation("synthetic-stack", fit_score=30, fit_tier="weak",
                                       recommendation="skip", fit_line="Weak fit — other stack.")
    result = apply_stack_gap_guard(annotation, {"raw_jd": "Requirements\n- Java experience."}, profile)
    assert "Java" in stack_reason(result)["detail"]
    assert result["fit_line"].startswith("Weak fit —")
    assert result["recommendation"] == "skip"


def test_null_projected_jd_uses_raw_jd_and_depth_can_override_broad_tags():
    from scraper.stack_requirements import apply_stack_gap_guard

    profile = safe_projection()
    profile["fit_signals"][0]["tags"].append("Java")
    profile["candidate"]["professional_depth"] = {"Java": ["directed-AI"]}
    result = apply_stack_gap_guard(structured_annotation("synthetic-stack"), {
        "jd_text": None, "raw_jd": "Requirements\n- Java experience.",
    }, profile)
    assert result["recommendation"] == "review"
