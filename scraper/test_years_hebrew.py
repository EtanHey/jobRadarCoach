"""Hebrew minimum years obey the existing strict seven-year gate."""

import pytest

from scraper.harvest import _has_blocking_years_requirement
from scraper.relevance import gate_rule


@pytest.mark.parametrize("description, blocked", [
    ("דרישות:\nלפחות 8 שנות ניסיון בפיתוח תוכנה", True),
    ("🎯 מה אנחנו מחפשים?\n✅ לפחות 8 שנות ניסיון בפיתוח תוכנה בסביבת Production", True),
    ("דרישות: 7–10 שנות ניסיון בפיתוח תוכנה", True),
    ("דרישות: 7 עד 10 שנות ניסיון בפיתוח תוכנה", True),
    ("דרישות: 6–10 שנות ניסיון בפיתוח תוכנה", False),
    ("דרישות: לפחות 6 שנות ניסיון בפיתוח תוכנה", False),
    ("דרישות: ניסיון של לפחות 7 שנים בפיתוח תוכנה", True),
    ("לחברה לפחות 20 שנות ניסיון בפיתוח תוכנה", False),
    ("דרישות: לפחות 8 שנות ניסיון - יתרון", False),
    ("יתרונות:\nלפחות 8 שנות ניסיון", False),
    ("דרישות: לא נדרש ניסיון של 8 שנים", False),
    ("דרישות: 8 שנות ניסיון אינן חובה", False),
    ("דרישות: לפחות 8 שנות ניסיון או תואר רלוונטי", False),
    ("דרישות: עד 8 שנות ניסיון", False),
    ("דרישות: 8.5 שנות ניסיון", False),
    ("Minimum of seven years of experience", True),
    ("Minimum of six years of experience", False),
])
def test_hebrew_seven_year_gate(description, blocked):
    assert _has_blocking_years_requirement(description) is blocked
    assert (gate_rule("Software Engineer", description) == "years-minimum-7-strict") is blocked
