import hashlib

import pytest

from scraper.forward_scoring_harness import canonical_json
from scraper.forward_scoring_inputs import (
    assemble_manifest,
    fetch_part2,
    parse_part1_answers,
    parse_part2_answers,
)


def _posting(key: str) -> dict[str, object]:
    return {
        "id": key,
        "title": f"Engineer {key}",
        "company": "Acme",
        "location": "Remote",
        "jd_text": "x" * 200,
    }


def _inputs():
    map1 = {
        "postings": [
            {"heading_number": index, "posting_id": f"db-{index}"}
            for index in range(1, 21)
        ]
    }
    map2 = {"postings": [{"p_number": f"P{index}"} for index in range(1, 11)]}
    answers1 = {index: "Pursue" for index in range(1, 21)}
    answers2 = {f"P{index}": "Maybe" for index in range(1, 11)}
    postings1 = {str(index): _posting(f"db-{index}") for index in range(1, 21)}
    postings2 = {f"P{index}": _posting(f"public-{index}") for index in range(1, 11)}
    return map1, answers1, postings1, map2, answers2, postings2


def test_answer_parsers_preserve_verbatim_qualifiers():
    part1 = "| 1 — Acme — Engineer | Maybe (leaning yes) | why |\n"
    part2 = "## P1. Acme — Engineer\n\nVerdict: Low pursue\n"

    assert parse_part1_answers(part1) == {1: "Maybe (leaning yes)"}
    assert parse_part2_answers(part2) == {"P1": "Low pursue"}


def test_manifest_freezes_exact_cohort_without_history_or_truth_in_inputs():
    inputs = _inputs()
    inputs[1][1] = "ambiguous answer"
    manifest = assemble_manifest({"projection_version": 1}, *inputs)

    assert len(manifest["expected_locators"]) == 30
    assert len(manifest["rows"]) == 29
    assert manifest["dropped"] == [
        {
            "locator": "part1:1:db-1",
            "part": 1,
            "reason": "ambiguous truth verdict",
        }
    ]
    for row in manifest["rows"]:
        frozen = row["frozen_input"]
        assert set(frozen) == {
            "professional_profile",
            "public_posting",
            "history_policy",
        }
        assert frozen["history_policy"] == "excluded"
        assert not ({"human_verdict", "verdict"} & set(frozen["public_posting"]))
        assert (
            row["input_sha256"]
            == hashlib.sha256(canonical_json(frozen).encode()).hexdigest()
        )


def test_manifest_rejects_answer_drift_and_truth_fields_in_posting():
    inputs = _inputs()
    inputs[1].pop(20)
    with pytest.raises(ValueError, match="exact 20/10 mapped cohort"):
        assemble_manifest({"projection_version": 1}, *inputs)

    inputs = _inputs()
    inputs[2]["1"]["verdict"] = "Pursue"
    with pytest.raises(ValueError, match="truth-label field"):
        assemble_manifest({"projection_version": 1}, *inputs)


def test_part2_fetch_rejects_non_ashby_locator_before_network():
    mapping = {
        "postings": [
            {
                "p_number": "P1",
                "url": "https://example.com/company/posting",
                "company": "Acme",
                "title": "Engineer",
            }
        ]
    }

    with pytest.raises(ValueError, match="invalid public Ashby locator"):
        fetch_part2(mapping)
