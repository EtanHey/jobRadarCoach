"""Synthetic wording from the owner's scored-72 residency counterexample."""
import pytest
from scraper.relevance import gate_rule

@pytest.mark.parametrize('jd,expected', [
    ('This role is remote, but candidates must be based in **United States**. We are hiring for this market specifically, so applicants should already be based in **United States**.', 'already-us-resident'),
    ('Candidates must already be based in the United States.', 'already-us-resident'),
    ('Applicants should already reside in the US.', 'already-us-resident'),
    ('You must already live in the United States.', 'already-us-resident'),
    ('Candidates must be based in the United States. Relocation is available.', None),
    ('Applicants should already be based in the United States or willing to relocate.', None),
    ('Already based in the US is preferred.', None),
    ('Our team is already based in the United States.', None),
])
def test_explicit_existing_us_residency(jd, expected):
    assert gate_rule('Full Stack Engineer', jd) == expected
