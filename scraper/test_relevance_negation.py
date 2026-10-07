"""Negated disqualifiers do not assert an owner-rejected requirement."""
import pytest
from scraper.relevance import gate_rule

@pytest.mark.parametrize('jd', [
    'A degree is not required. Hands-on product delivery is required.',
    'No degree required.',
    'A BSc degree is not mandatory.',
    'This is not an equity-only role; salary is paid.',
    '7+ years of software experience is not required.',
    'Marketing background is not mandatory.',
    'A high degree of ownership is required.',
    "No bachelor's degree required.",
    "No formal bachelor's degree is required.",
    "A bachelor's degree isn't required.",
    "A bachelor's degree isn’t mandatory.",
    "Bachelor's and master's degrees aren't required.",
    "A marketing background isn't required.",
    "SAP development expertise isn't mandatory.",
    "7+ years building security solutions isn't required.",
])
def test_negated_hard_negatives_pass(jd):
    assert gate_rule('Frontend Engineer', jd) is None


@pytest.mark.parametrize('jd,rule', [
    ("A bachelor's degree is required.", 'mandatory-degree'),
    ("A formal bachelor's degree is mandatory.", 'mandatory-degree'),
    ('A marketing background is required.', 'specialist-required'),
    ('SAP development expertise is mandatory.', 'specialist-required'),
])
def test_positive_requirement_controls(jd, rule):
    assert gate_rule('Frontend Engineer', jd) == rule
