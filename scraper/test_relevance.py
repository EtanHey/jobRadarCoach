import pytest

from scraper.relevance import gate_rule


@pytest.mark.parametrize('title,jd,rule', [
    ('Principal Engineer', '', 'leadership-title-strict'),
    ('SWE III', 'Active clearance required. 5 days onsite. Salary 15000', None),
    ('Platform Engineer', 'Kubernetes Kafka expertise required', None),
    ('ML Engineer', 'Strong Python required', None),
    ('QA Automation Engineer', '', 'pure-qa-title'),
    ('Junior Frontend and Automation Developer', '', None),
    ('Technical Support Engineer', '', 'support-title'),
    ('Technical Co-Founder / CTO', '', 'technical-cofounder-title'),
    ('Founding Engineer', 'Gambling company. Long hours', None),
    ('Engineer', 'Compensation: equity-only, no salary', 'equity-only'),
    ('Engineer', 'Must already live in the United States', 'already-us-resident'),
    ('Engineer', 'Eligible to relocate to the US. Able to obtain clearance', None),
    ('AI/ML Engineer (Mid-level to Principal)', '', None),
    ('Java Developer', '', 'incompatible-stack-title'),
    ('Frontend Developer (JavaScript, CSS)', '', None),
    ('Python Engineer', 'Strong Python expertise required', None),
    ('Engineer', '7+ years of software experience', 'years-minimum-7-strict'),
    ('Engineer', '6-10 years of software experience', None),
    ('Junior Frontend Engineer', 'Acme builds on more than 25 years of experience', None),
    ('Engineer', 'A bachelor degree is required', 'mandatory-degree'),
    ('Engineer', 'A bachelor degree is required or equivalent experience', None),
    ('Backend Engineer', 'Experience with Kafka required', None),
    ('Data Product Engineer', 'React TypeScript BigQuery Snowflake Docker', None),
    ('Engineer', '3 years building security solutions required', 'specialist-required'),
    ('Senior Full Stack Engineer', '5+ years experience. Python is a plus. Relocation, defense, crypto, temporary', None),
])
def test_calibrated_rules_preserve_exceptions(title, jd, rule):
    assert gate_rule(title, jd) == rule
