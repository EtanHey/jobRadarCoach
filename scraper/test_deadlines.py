"""Synthetic explicit-deadline and conservative rejection controls."""
from datetime import datetime, timezone

import pytest

from scraper.deadlines import extract_deadline
from scraper.ats_liveness import project_liveness


@pytest.mark.parametrize("text", [
    "Applications close on October 18th, 2026.",
    "Application deadline: 2026-10-18",
    "מועד אחרון להגשת מועמדות: 18 באוקטובר 2026",
    "ניתן להגיש מועמדות עד 18.10.2026",
])
def test_explicit_calendar_deadline_preserves_quote(text):
    result = extract_deadline(text)
    # Date-only closure waits until that civil day has ended in every timezone.
    assert result["application_deadline"] == "2026-10-19T12:00:00Z"
    assert result["application_deadline_evidence_quote"] == text
    assert result["application_deadline_remark"] is None


@pytest.mark.parametrize("text", [
    "Applications close on October 18th.",  # No year, even with other dated events.
    "Application deadline: 03/04/2026",  # Ambiguous numeric order.
    "Application deadline: 2026-02-30",
    "Application deadline: 18 October 2026 at 5pm",  # No timezone.
    "מועד אחרון להגשת מועמדות: בקרוב",
    "Applications close on October 18, 2026 or earlier if filled.",
])
def test_unparseable_or_conditional_dates_do_not_close(text):
    result = extract_deadline(text)
    assert result["application_deadline"] is None
    assert result["application_deadline_evidence_quote"] == text
    assert result["application_deadline_remark"]


@pytest.mark.parametrize("text", [
    "Project deadline: October 18, 2026",
    "The bootcamp starts on 2026-10-18.",
    "No application deadline: 2026-10-18",
    "אין מועד אחרון להגשת מועמדות: 18.10.2026",
    "Application deadline experience required.",
])
def test_unrelated_or_negated_frames_are_not_deadlines(text):
    assert extract_deadline(text)["application_deadline_evidence_quote"] is None


def test_zoned_instant_and_passed_deadline_override_fresh_open_page():
    quote = "Application deadline: 2026-10-18T17:00:00+03:00"
    evidence = {"alive": True, "liveness_checked_at": "2026-10-18T14:00:00Z",
                **extract_deadline(quote)}
    assert project_liveness(evidence, now=datetime(2026, 10, 18, 14, tzinfo=timezone.utc))["alive"] is True
    projected = project_liveness(evidence, now=datetime(2026, 10, 18, 14, 1, tzinfo=timezone.utc))
    assert projected["state"] == "deadline_passed" and projected["alive"] is False
    assert evidence["alive"] is True  # Page observation remains separate.


@pytest.mark.parametrize("extension", [
    "Application deadline extended to: 2026-10-25",
    "Application deadline has been extended to October 25th, 2026.",
    "המועד להגשת מועמדות הוארך עד 25 באוקטובר 2026",
])
def test_only_explicit_extension_resolves_conflicting_dates(extension):
    old = "Application deadline: 2026-10-18"
    result = extract_deadline(old + "\n" + extension)
    assert result["application_deadline"] == "2026-10-26T12:00:00Z"
    assert result["application_deadline_evidence_quote"] == extension
    assert extract_deadline(old + "\nApplication deadline: 2026-10-25")["application_deadline"] is None


def test_missing_year_is_not_borrowed_from_posting_or_selection_dates():
    text = "Selection stages: 26.10.26 and 04.11.26.\n**Applications close on October 18th.**"
    result = extract_deadline(text)
    assert result["application_deadline"] is None
    assert result["application_deadline_evidence_quote"] == "**Applications close on October 18th.**"


def test_unambiguous_month_first_numeric_date():
    assert extract_deadline("Application deadline: 12-30-2026")["application_deadline"] == "2026-12-31T12:00:00Z"


def test_date_only_deadline_does_not_infer_an_employer_timezone():
    evidence = {"alive": True, "liveness_checked_at": "2026-10-19T11:00:00Z",
                **extract_deadline("Application deadline: 2026-10-18")}
    assert project_liveness(evidence, now=datetime(2026, 10, 19, 12, tzinfo=timezone.utc))["alive"] is True
    assert project_liveness(evidence, now=datetime(2026, 10, 19, 12, 1, tzinfo=timezone.utc))["alive"] is False
