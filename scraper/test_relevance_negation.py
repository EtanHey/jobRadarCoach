"""Negated disqualifiers do not assert an owner-rejected requirement."""
import pytest
from scraper.relevance import gate_rule

@pytest.mark.parametrize('jd', [
    'A degree is not required. Hands-on product delivery is required.',
    'No degree required.',
    'A BSc degree is not mandatory.',
    'This is not an equity-only role; salary is paid.',
])
def test_negated_hard_negatives_pass(jd):
    assert gate_rule('Frontend Engineer', jd) is None
