from __future__ import annotations

import copy
from datetime import date

import pytest

from classifier import projection
from scraper.test_annotate import safe_projection


PRIVATE = "PRIVATE_PROJECTION_SENTINEL"


def profile_snapshot() -> dict[str, object]:
    safe = safe_projection()
    candidate = safe["candidate"]
    candidate["professional_depth"] = {"TypeScript": ["hands-on"]}
    return {
        "contract_version": 1,
        "candidate.positioning": candidate["positioning"],
        "candidate.tenure_years": candidate["tenure_years"],
        "candidate.location": candidate["location"],
        "candidate.fit_terms": candidate["fit_terms"],
        "candidate.open_to.geographies": candidate["open_to"]["geographies"],
        "candidate.open_to.work_modes": candidate["open_to"]["work_modes"],
        "candidate.open_to.relocation": candidate["open_to"]["relocation"],
        "candidate.preferences.product_company": candidate["preferences"][
            "product_company"
        ],
        "candidate.preferences.experience_gap": candidate["preferences"][
            "experience_gap"
        ],
        "candidate.professional_depth": candidate["professional_depth"],
        "fit_signals": safe["fit_signals"],
        "constraints.global_never_claims": safe["constraints"][
            "global_never_claims"
        ],
        "constraints.evidence_scoped_prohibitions": safe["constraints"][
            "evidence_scoped_prohibitions"
        ],
        "runtime.brain": "ollama",
        "people": [PRIVATE],
        "connectors": {"private": PRIVATE},
    }


def posting(raw_jd: object | None = None) -> dict[str, object]:
    return {
        "id": "posting-1",
        "title": "Backend Engineer",
        "company": "Public Example",
        "location": "Tel Aviv",
        "raw_jd": raw_jd
        if raw_jd is not None
        else "Build public TypeScript backend services. " * 10,
        "human_verdict": "interesting",
    }


def test_profile_contract_preserves_only_validated_annotation_projection() -> None:
    validated = projection.profile_contract(profile_snapshot())

    assert validated["candidate"]["positioning"]
    assert validated["candidate"]["professional_depth"] == {
        "TypeScript": ["hands-on"]
    }
    assert validated["fit_signals"]
    assert PRIVATE not in repr(validated)


@pytest.mark.parametrize("mutation", ["blank", "bad-depth", "unverified"])
def test_profile_contract_rejects_invalid_professional_evidence(mutation: str) -> None:
    snapshot = profile_snapshot()
    if mutation == "blank":
        snapshot["candidate.positioning"] = " "
    elif mutation == "bad-depth":
        snapshot["candidate.professional_depth"] = {"TypeScript": ["expert"]}
    else:
        signals = copy.deepcopy(snapshot["fit_signals"])
        signals[0]["status"] = "draft"
        snapshot["fit_signals"] = signals

    with pytest.raises(ValueError):
        projection.profile_contract(snapshot)


def test_public_posting_maps_substantive_raw_jd_and_human_verdict() -> None:
    public = projection.public_posting(posting())

    assert "raw_jd" not in public
    assert len(public["jd_text"]) >= projection.MIN_JD_CHARS
    assert public["human_verdict"] == "interesting"


@pytest.mark.parametrize("raw_jd", [None, "", "title only", 42])
def test_public_posting_rejects_missing_or_sparse_jd(raw_jd: object) -> None:
    candidate = posting(raw_jd)
    if raw_jd is None:
        candidate["raw_jd"] = None

    with pytest.raises(ValueError):
        projection.public_posting(candidate)


def test_history_projection_is_bounded_public_and_date_normalized() -> None:
    projected = projection.history_projection(
        [
            {
                "history_id": "history-1",
                "company": "Public Company",
                "role": "Engineer",
                "application_date": date(2026, 9, 7),
                "outcome": None,
                "private_notes": PRIVATE,
            }
        ]
    )

    assert projected == [
        {
            "evidence_id": "application-history:history-1",
            "company": "Public Company",
            "role": "Engineer",
            "application_date": "2026-09-07",
            "outcome": None,
        }
    ]


def test_history_projection_rejects_duplicates_and_overflow() -> None:
    row = {"history_id": "same", "company": "Public Company"}
    with pytest.raises(ValueError):
        projection.history_projection([row, row])
    with pytest.raises(ValueError):
        projection.history_projection(
            [
                {"history_id": str(index), "company": "Public Company"}
                for index in range(projection.MAX_HISTORY_ENTRIES + 1)
            ]
        )


@pytest.mark.parametrize("nested", [False, True])
def test_profile_contract_rejects_unknown_fit_signal_fields(nested: bool) -> None:
    snapshot = profile_snapshot()
    signal = copy.deepcopy(snapshot["fit_signals"][0])
    target = signal["ownership"] if nested else signal
    target["private_notes"] = PRIVATE
    snapshot["fit_signals"] = [signal]
    with pytest.raises(ValueError, match="fields"):
        projection.profile_contract(snapshot)
