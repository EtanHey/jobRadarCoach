from __future__ import annotations

from copy import deepcopy

import pytest

from extractor import core
from extractor.evidence import ExtractionValidationError, validate_facts
from scraper.brain import BrainResult


UNSUPPORTED = [
    "This job is based in Cedar Bay, with no option to work from our Harbor City headquarters.",
    "This job is based in Cedar Bay, and daily onsite presence at our Harbor City headquarters is not required or offered.",
    "This job is not a position based at our headquarters in Harbor City.",
    "This job is based in Cedar Bay; another position is based at our headquarters in Harbor City.",
    "This job is based in Cedar Bay, while a different job is based at our headquarters in Harbor City.",
    "Employee benefits: the option to work from our Harbor City headquarters applies only to corporate staff, not this job.",
    "This job is based in Cedar Bay; the previous position was a job based at our headquarters in Harbor City.",
    "The option to work from our Harbor City headquarters is not available for this job.",
    "There is no longer an option to work from our Harbor City headquarters.",
    "Daily onsite presence at our Harbor City headquarters is prohibited.",
    "The role is not based at our headquarters in Harbor City.",
    "The role was based at our headquarters in Harbor City.",
    "The position is based at our headquarters in Harbor City for another vacancy.",
    "Daily onsite presence at our Harbor City headquarters is required only for corporate staff.",
    "The option to work from our Harbor City headquarters is reserved for other employees.",
    "The option to work from our Harbor City headquarters does not apply to this role.",
    "The role is based in Harbor City, but this location is no longer offered.",
    "The option to work from our Harbor City headquarters is only available to corporate staff.",
    "Daily onsite presence at our Harbor City headquarters applies to corporate staff only.",
    "Previously, the position based at our headquarters in Harbor City was open.",
    "Formerly the option to work from our Harbor City headquarters was available.",
    "Another position comes with the option to work from our Harbor City headquarters.",
    "A previous job included parking and daily onsite presence at our Harbor City headquarters.",
    "Another position offers flexible hours, but daily onsite presence at our Harbor City headquarters is required.",
    "Another position is open, and the job is based at our headquarters in Harbor City.",
]


def location_facts(quote: str) -> dict[str, object]:
    candidate = {
        field: {"value": None, "evidence_quote": None}
        for field in ("location", "remote", "seniority", "salary")
    }
    candidate["stack"] = []
    candidate["location"] = {"value": "Harbor City", "evidence_quote": quote}
    return candidate


@pytest.mark.parametrize("jd", UNSUPPORTED)
@pytest.mark.parametrize("full_quote", [False, True], ids=["city-only", "full-clause"])
def test_unoffered_or_other_role_location_is_rejected(jd: str, full_quote: bool) -> None:
    candidate = location_facts(jd if full_quote else "Harbor City")
    raw_jd = jd + " Build reliable backend services with the engineering team."

    def runner(request, *_args, **_kwargs):
        return BrainResult(deepcopy(candidate), "codex", "fixture-model", request=request)

    for extract in (
        lambda: validate_facts(candidate, raw_jd),
        lambda: core.extract_posting(
            {"raw_jd": raw_jd, "location": "Cedar Bay"}, {}, runner=runner,
        ),
    ):
        with pytest.raises(ExtractionValidationError) as error:
            extract()
        assert (error.value.category, error.value.field) == ("location_context", "location")


@pytest.mark.parametrize("jd", [
    "This job is based at our Harbor City headquarters, while another job is based in Cedar Bay.",
    "We cannot provide parking, but this job is based at our headquarters in Harbor City.",
    "This job is based at our headquarters in Harbor City, but parking is not available.",
    "Not only is this job based at our headquarters in Harbor City, it offers flexible hours.",
    "This job is based at our headquarters in Harbor City; the previous role was based in Cedar Bay.",
    "Our headquarters are in Harbor City. This role is based in Harbor City.",
    "Another job is based in Cedar Bay, while this job is based at our headquarters in Harbor City.",
    "This job is based at our headquarters in Harbor City, while the previous role was based in Cedar Bay.",
    "Location: Daily onsite presence at our Harbor City headquarters in alignment with our policy Complete other responsibilities across different operating conditions.",
])
def test_positive_location_is_scoped_to_this_role(jd: str) -> None:
    validate_facts(location_facts("Harbor City"), jd)
