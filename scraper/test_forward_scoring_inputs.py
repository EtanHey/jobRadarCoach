import copy
import io
import json

import pytest

from classifier import request as scoring_request
from scraper import forward_scoring_inputs as inputs_module
from scraper.forward_scoring_inputs import (
    assemble_manifest,
    fetch_part2,
    parse_part1_answers,
    parse_part2_answers,
    parse_part3_answers,
    verify_freeze_receipt,
)
from scraper.test_annotate import safe_projection


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
    for index, row in enumerate(map2["postings"], 1):
        row["url"] = f"https://jobs.ashbyhq.com/board/two-{index}"
    map3 = {
        "postings": [
            {
                "p_number": f"P{index}",
                "url": f"https://jobs.ashbyhq.com/board/three-{index}",
            }
            for index in range(11, 21)
        ]
    }
    answers1 = {index: "Pursue" for index in range(1, 21)}
    answers2 = {f"P{index}": "Maybe" for index in range(1, 11)}
    answers3 = {
        **{
            f"P{index}": {"verbatim": "Pursue", "comment": f"comment-{index}"}
            for index in range(11, 14)
        },
        **{
            f"P{index}": {"verbatim": "Maybe", "comment": f"comment-{index}"}
            for index in range(14, 17)
        },
        **{
            f"P{index}": {"verbatim": "No", "comment": f"comment-{index}"}
            for index in range(17, 21)
        },
    }
    postings1 = {str(index): _posting(f"db-{index}") for index in range(1, 21)}
    postings2 = {f"P{index}": _posting(f"public-{index}") for index in range(1, 11)}
    postings3 = {f"P{index}": _posting(f"public-{index}") for index in range(11, 21)}
    return (
        map1,
        answers1,
        postings1,
        map2,
        answers2,
        postings2,
        map3,
        answers3,
        postings3,
    )


def test_answer_parsers_preserve_verbatim_qualifiers():
    part1 = "| 1 — Acme — Engineer | Maybe (leaning yes) | why |\n"
    part2 = "## P1. Acme — Engineer\n\nVerdict: Low pursue\n"
    part3 = '- P16 Loora — Frontend: **Pursue (strong)** — "referral signal"\n'

    assert parse_part1_answers(part1) == {1: "Maybe (leaning yes)"}
    assert parse_part2_answers(part2) == {"P1": "Low pursue"}
    assert parse_part3_answers(part3) == {
        "P16": {"verbatim": "Pursue (strong)", "comment": '"referral signal"'}
    }


def test_manifest_freezes_exact_cohort_without_history_or_truth_in_inputs():
    inputs = _inputs()
    inputs[1][1] = "ambiguous answer"
    manifest = assemble_manifest(safe_projection(), *inputs)

    assert len(manifest["expected_locators"]) == 40
    assert len(manifest["rows"]) == 39
    assert manifest["dropped"] == [
        {
            "locator": "part1:1:db-1",
            "part": 1,
            "reason": "ambiguous truth verdict",
            "gold": {"verbatim": "ambiguous answer", "label": None},
        }
    ]
    assert [
        sum(row["part"] == part for row in manifest["rows"]) for part in (1, 2, 3)
    ] == [19, 10, 10]
    part3 = next(row for row in manifest["rows"] if row["part"] == 3)
    assert part3["gold"]["comment"].startswith("comment-")
    for row in manifest["rows"]:
        frozen = row["frozen_input"]
        assert set(frozen) == {
            "hosted_payload",
            "reference_validation_profile",
            "history_policy",
        }
        assert frozen["history_policy"] == "excluded"
        assert set(frozen["hosted_payload"]) == {
            "professional_profile",
            "public_posting",
        }
        assert not (
            {"human_verdict", "verdict"}
            & set(frozen["hosted_payload"]["public_posting"])
        )
    verify_freeze_receipt(manifest)


def test_ambiguous_verbatim_truth_changes_the_freeze_receipt():
    first_inputs = _inputs()
    first_inputs[1][1] = "Probably pursue"
    first = assemble_manifest(safe_projection(), *first_inputs)
    second_inputs = _inputs()
    second_inputs[1][1] = "ambiguous answer"
    second = assemble_manifest(safe_projection(), *second_inputs)

    assert first["dropped"][0]["gold"] == {
        "verbatim": "Probably pursue",
        "label": None,
    }
    assert second["dropped"][0]["gold"] == {
        "verbatim": "ambiguous answer",
        "label": None,
    }
    assert first["freeze_receipt"]["sha256"] != second["freeze_receipt"]["sha256"]


def test_manifest_rejects_answer_drift_and_truth_fields_in_posting():
    inputs = _inputs()
    inputs[1].pop(20)
    with pytest.raises(ValueError, match="exact 20/10/10 mapped cohort"):
        assemble_manifest(safe_projection(), *inputs)

    inputs = _inputs()
    inputs[2]["1"]["verdict"] = "Pursue"
    with pytest.raises(ValueError, match="truth-label field"):
        assemble_manifest(safe_projection(), *inputs)


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


@pytest.mark.parametrize(
    ("parser", "text"),
    [
        (
            parse_part1_answers,
            "| 1 — A — E | Pursue | x |\n| 1 — A — E | No | y |\n",
        ),
        (
            parse_part2_answers,
            "## P1. A — E\nVerdict: Pursue\nVerdict: No\n",
        ),
        (
            parse_part2_answers,
            "## P1. A — E\nVerdict: Pursue\n## P1. A — E\nVerdict: Pursue\n",
        ),
    ],
)
def test_answer_parsers_reject_duplicate_truth(parser, text):
    with pytest.raises(ValueError, match="duplicate"):
        parser(text)


@pytest.mark.parametrize(
    "mutation",
    ["part1-key", "part1-posting", "part2-key", "public-url"],
)
def test_manifest_rejects_duplicate_mapping_identity(mutation):
    values = list(_inputs())
    map1, map2, map3 = values[0], values[3], values[6]
    if mutation == "part1-key":
        map1["postings"][1]["heading_number"] = 1
    elif mutation == "part1-posting":
        map1["postings"][1]["posting_id"] = map1["postings"][0]["posting_id"]
    elif mutation == "part2-key":
        map2["postings"][1]["p_number"] = "P1"
    else:
        map3["postings"][0]["url"] = map2["postings"][0]["url"]

    with pytest.raises(ValueError, match="duplicate"):
        assemble_manifest(safe_projection(), *values)


def test_manifest_rejects_captured_posting_key_drift():
    values = list(_inputs())
    values[2].pop("20")
    with pytest.raises(ValueError, match="captured posting keys"):
        assemble_manifest(safe_projection(), *values)

    values = list(_inputs())
    values[5]["extra"] = _posting("extra")
    with pytest.raises(ValueError, match="captured posting keys"):
        assemble_manifest(safe_projection(), *values)


def test_frozen_hosted_payload_is_byte_equal_to_production_request_projection():
    profile = safe_projection()
    profile["candidate"]["location"] = "WITHHELD_LOCATION_SENTINEL"
    profile["candidate"]["open_to"] = {"private": "WITHHELD_OPEN_TO_SENTINEL"}
    manifest = assemble_manifest(profile, *_inputs())
    row = manifest["rows"][0]
    request = scoring_request.build_request(
        row["frozen_input"]["hosted_payload"]["public_posting"], profile, []
    )
    lines = request.prompt.splitlines()
    projected = {
        "professional_profile": json.loads(
            lines[lines.index("Professional fit profile:") + 1]
        ),
        "public_posting": json.loads(lines[lines.index("Public posting:") + 1]),
    }

    assert projected == row["frozen_input"]["hosted_payload"]
    assert "WITHHELD_" not in json.dumps(projected, sort_keys=True)
    assert "application_history" not in projected
    assert "verdict" not in json.dumps(projected, sort_keys=True).casefold()


def test_freeze_receipt_binds_truth_cohort_drop_and_inputs_not_predictions():
    values = list(_inputs())
    values[1][1] = "Probably pursue"
    manifest = assemble_manifest(safe_projection(), *values)
    manifest["rows"][0]["reference"] = {"fit_score": 80}
    manifest["rows"][0]["jev"].append({"answer": "pursue"})
    verify_freeze_receipt(manifest)

    mutations = []
    for target, key, value in (
        (("rows", 0, "gold"), "verbatim", "No"),
        (("rows", 0), "locator", "changed"),
        (("rows", 0), "part", 3),
        (("dropped", 0), "reason", "changed"),
    ):
        candidate = copy.deepcopy(manifest)
        item = candidate[target[0]][target[1]]
        if len(target) == 3:
            item = item[target[2]]
        item[key] = value
        mutations.append(candidate)
    for candidate in mutations:
        with pytest.raises(ValueError, match="freeze receipt"):
            verify_freeze_receipt(candidate)


@pytest.mark.parametrize(
    ("job_urls", "listed"),
    [
        (["https://jobs.ashbyhq.com/wrong/abc"], True),
        (["https://jobs.ashbyhq.com/board/abc-extra"], True),
        (["https://jobs.ashbyhq.com/board/xabc"], True),
        (["https://jobs.ashbyhq.com/board/abc?x=1"], True),
        (["https://jobs.ashbyhq.com/board/abc#x"], True),
        (["https://jobs.ashbyhq.com/board/abc"], False),
        (
            [
                "https://jobs.ashbyhq.com/board/abc",
                "https://jobs.ashbyhq.com/board/abc",
            ],
            True,
        ),
    ],
)
def test_part2_fetch_requires_exact_decoded_job_identity(monkeypatch, job_urls, listed):
    jobs = [
        {
            "jobUrl": url,
            "isListed": listed,
            "title": "Engineer",
            "location": "Remote",
            "descriptionPlain": "x" * 200,
        }
        for url in job_urls
    ]
    monkeypatch.setattr(
        inputs_module,
        "urlopen",
        lambda *_args, **_kwargs: io.StringIO(json.dumps({"jobs": jobs})),
    )
    mapping = {
        "postings": [
            {
                "p_number": "P1",
                "url": "https://jobs.ashbyhq.com/board/abc",
                "company": "Acme",
                "title": "Engineer",
            }
        ]
    }

    with pytest.raises(ValueError, match="not uniquely live"):
        fetch_part2(mapping)
