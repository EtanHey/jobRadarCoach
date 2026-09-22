from __future__ import annotations

from pathlib import Path
import os

from scraper import e6_retrospective as e6


def test_gold_loader_keeps_only_final_his_verdicts(tmp_path: Path) -> None:
    source_c = tmp_path / "C.md"
    source_d = tmp_path / "D.md"
    source_c.write_text(
        "| company | role | verdict | words | date | source | CURRENT? |\n"
        "|---|---|---|---|---|---|---|\n"
        "| Alpha | Engineer | APPLIED — HIS | yes | now | raw:1 | yes |\n"
        "| Beta | Engineer | REJECTED — THEIRS | no | now | raw:2 | closed |\n"
        "| Gamma | Engineer | COACH-FILTERED | — | now | raw:3 | yes |\n",
        encoding="utf-8",
    )
    source_d.write_text(
        "| Company | Role | Verdict | His words | Date | Source | Whose |\n"
        "|---|---|---|---|---|---|---|\n"
        "| Delta | Engineer | declined | no | now | raw:4 | HIS |\n",
        encoding="utf-8",
    )
    gold, excluded = e6.load_gold(source_c, source_d)
    assert [(row.company, row.label) for row in gold] == [
        ("Alpha", "positive"), ("Delta", "negative")
    ]
    assert len(excluded) == 2


def test_jev_state_is_byte_identical_professional_projection() -> None:
    professional = {"projection_version": 1, "candidate": {"positioning": "public"}}
    posting = e6.Posting(
        "00000000-0000-0000-0000-000000000001", "1", "https://example.com/1",
        "Engineer", "Example", "Remote", "x" * 200, {}, "codex", "configured:gpt-5.6-terra",
    )
    state = e6.jev_state(posting, professional)
    assert e6.canonical_json(state["professional_profile"]) == e6.canonical_json(professional)
    assert e6.jev_sanitizer(state) == state


def test_divergence_sample_frame_includes_subfloor_abstentions() -> None:
    rows = [
        {"posting_id": "a", "jev_prediction": "abstain", "terra_prediction": "pursue", "public_posting": {}},
        {"posting_id": "b", "jev_prediction": "no", "terra_prediction": "pursue", "public_posting": {}},
        {"posting_id": "c", "jev_prediction": "pursue", "terra_prediction": "pursue", "public_posting": {}},
    ]
    sample, population = e6.sample_divergences(rows, size=60, seed=1)
    assert population == 2
    assert {row["posting_id"] for row in sample} == {"a", "b"}
    assert any("abstain" in {row["option_a"], row["option_b"]} for row in sample)


def test_each_run_gets_its_own_wilson_interval() -> None:
    rows = [
        {"gold": "positive", "answer": answer, "confidence": 0.9}
        for answer in ("pursue", "no")
    ]
    first = e6.gold_metrics(rows[:1], 0.70)
    second = e6.gold_metrics(rows[1:], 0.70)
    assert first["recall_wilson_95"] != second["recall_wilson_95"]


def test_tls_ca_bundle_preserves_explicit_operator_setting(monkeypatch) -> None:
    monkeypatch.setenv("SSL_CERT_FILE", "/operator/ca.pem")
    assert e6.configure_tls_ca_bundle() == "/operator/ca.pem"
    assert os.environ["SSL_CERT_FILE"] == "/operator/ca.pem"


def test_section_seven_seniority_titles_are_gates() -> None:
    assert e6._is_gate("Example", "Principal Engineer") is True
    assert e6._is_gate("Example", "Head-of Engineering") is True


def test_truth_file_never_scraped_aliases_are_normalized() -> None:
    assert e6._company_key("Yara AI") in e6.NEVER_SCRAPED
    assert e6._company_key("Palo Alto Networks") in e6.NEVER_SCRAPED
