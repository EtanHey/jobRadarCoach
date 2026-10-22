"""Frozen triage shapes; no private scoring or candidate data."""
import json
from pathlib import Path

import pytest

from scraper.employer_identity import resolve_employer

ROWS = json.loads((Path(__file__).parents[1] / 'test_support/fixtures/employer_identity.json').read_text())


@pytest.mark.parametrize('row', ROWS, ids=lambda row: row['company'])
def test_snapshot_identity(row):
    result = resolve_employer(row['company'], row['raw_jd'], row['source'])
    expected = {'EngRadar': 'Monday.com', 'Torentify': None, 'Wix': 'Wix'}
    assert result['publisher'] == row['company']
    assert result['hiring_employer'] == expected[row['company']]
    if result['hiring_employer']:
        assert result['employer_evidence'] in row['raw_jd'] or result['employer_evidence'].startswith('source:')


@pytest.mark.parametrize('jd, expected', [
    ('Recruiting on behalf of Acme Labs for an engineer.', 'Acme Labs'),
    ('Our client Acme Labs is hiring an engineer.', 'Acme Labs'),
    ('Acme Labs is hiring an engineer.', 'Acme Labs'),
    ('Our client is a leading fintech company.', None),
    ('**About The Company**\n\nOur mission at Ōura is to empower people.', None),
    ('This employer is hiring engineers.', None),
    ('Acme Labs is hiring engineers.\nBeta Labs is hiring engineers.', None),
    ('Experience with React and Monday.com is required.', None),
    ('We are hiring engineers. Acme Labs is hiring engineers.', None),
])
def test_explicit_names_only(jd, expected):
    assert resolve_employer('Torentify', jd, 'linkedin')['hiring_employer'] == expected


def test_absent_agency_evidence_is_not_direct():
    assert resolve_employer('New Publisher', 'Build React apps.', 'linkedin')['hiring_employer'] is None


def test_publisher_catalog_matches_browser_catalog():
    from scraper.employer_publishers import PUBLISHERS
    assert list(PUBLISHERS) == json.loads((Path(__file__).parents[1] / 'ui/lib/employer-publishers.json').read_text())


@pytest.mark.parametrize('publisher,jd', [
    ('AgileGrid Solutions', '**About The Company**\n\nQuik Hire Staffing is a leading provider of innovative staffing solutions connecting professionals with client organizations.\n\n**About The Role**\n\nWe are seeking a Frontend Developer for a global software company.'),
    ('מרטנס | Mertens – מקבוצת מלם תים', 'Mertens - MalamTeam is hiring a Backend Developer to join a leading organization in the Gush Dan area'),
    ('New Publisher', '**About The Company**\n\nTalent Bridge is a recruiting firm placing engineers with clients.\n\n**About The Role**\n\nWe seek an engineer for an unnamed client.'),
    ('New Publisher', 'Talent Bridge is hiring a developer for our client.'),
])
def test_intermediary_is_not_hiring_employer(publisher, jd):
    result = resolve_employer(publisher, jd, 'linkedin')
    assert result['hiring_employer'] is None
    assert result['agency_evidence'] in jd


@pytest.mark.parametrize('role,expected', [
    ('Scribe in San Francisco is seeking a Senior Frontend Engineer.', 'Scribe'),
    ('Scribe is seeking a Senior Frontend Engineer.', 'Scribe'),
    ('Scribe is seeking an engineer.\nBeta Labs is hiring an engineer.', None),
])
def test_role_identity_overrides_conflicting_blurb(role, expected):
    jd = '**About The Company**\n\nCantos Ventures is an investment firm.\n\n**About The Role**\n\n' + role
    result = resolve_employer('Netrolynx AI', jd, 'linkedin')
    assert result['hiring_employer'] == expected
    if expected:
        assert 'Scribe' in result['employer_evidence']
        assert 'Cantos' not in result['employer_evidence']


ALIASES = [
    ('Alice (Formerly ActiveFence)', 'Alice'),
    ('BMC Software', 'BMC'),
    ('EyeContact Dx', 'EyeContact'),
    ('IAI - Israel Aerospace Industries', 'Israel Aerospace Industries Aviation Division'),
    ('Ness Technologies | נס טכנולוגיות', 'NESS FORCE'),
    ('Ness Technologies | נס טכנולוגיות', 'Ness'),
    ('Nova Ltd.', 'Nova'),
    ('Parsons Corporation', 'Parsons'),
    ('Ripple Analytics', 'Ripple'),
    ('SWAKIO™', 'SWAKIO'),
]


@pytest.mark.parametrize('publisher,employer', ALIASES)
def test_reviewed_alias_is_not_different_employer(publisher, employer):
    result = resolve_employer(publisher, f'**About The Company**\n\n{employer} is building software.', 'linkedin')
    assert result['hiring_employer'] == employer
    assert result['relationship'] == 'alias'


def test_agency_can_name_an_actual_client():
    jd = '**About The Company**\n\nTalent Bridge is a staffing firm.\n\n**About The Role**\n\nOur client Acme Labs is hiring a developer.'
    result = resolve_employer('New Publisher', jd, 'linkedin')
    assert result['hiring_employer'] == 'Acme Labs'
    assert result['agency_evidence'] in jd


def test_role_conflict_does_not_fall_back_to_ats_publisher():
    jd = 'Acme Labs is hiring an engineer.\nBeta Labs is hiring an engineer.'
    assert resolve_employer('Example', jd, 'greenhouse')['hiring_employer'] is None


@pytest.mark.parametrize('jd', [
    'Mobileye is looking for an engineer to join our Algorithms organization.',
    'NVIDIA is seeking an engineer to join our System Product Engineering organization.',
])
def test_internal_organization_is_not_agency_evidence(jd):
    publisher = jd.split()[0]
    result = resolve_employer(publisher, jd, 'linkedin')
    assert result['hiring_employer'] == publisher
    assert result['agency_evidence'] is None


def test_unnamed_role_client_does_not_fall_back_to_company_blurb():
    jd = '**About The Company**\n\nAcme Labs is a software company.\n\n**About The Role**\n\nTalent Bridge is hiring a developer for a client of ours.'
    assert resolve_employer('New Publisher', jd, 'linkedin')['hiring_employer'] is None


def test_reviewed_alias_catalog_matches_browser():
    from scraper.employer_aliases import ALIASES
    assert ALIASES == json.loads((Path(__file__).parents[1] / 'ui/lib/employer-aliases.json').read_text())


def test_unlisted_publisher_can_have_explicit_unnamed_client_evidence():
    jd = 'Our client is a leading fintech company seeking an engineer.'
    result = resolve_employer('New Publisher', jd, 'linkedin')
    assert result['hiring_employer'] is None
    assert result['agency_evidence'] == jd


@pytest.mark.parametrize('jd', [
    'Our client success team builds developer tools.',
    'Our client SDK supports React.',
])
def test_client_product_or_team_is_not_agency_evidence(jd):
    result = resolve_employer('New Publisher', jd, 'linkedin')
    assert result['hiring_employer'] is None
    assert result['agency_evidence'] is None


def test_staffing_software_is_not_a_staffing_intermediary():
    jd = '**About The Company**\n\nAcme Labs is a staffing software platform.'
    result = resolve_employer('Acme Labs', jd, 'linkedin')
    assert result['hiring_employer'] == 'Acme Labs'
    assert result['agency_evidence'] is None


def test_reviewed_alldus_repost_keeps_client_unknown():
    jd = ('**About The Company**\n\nAlldus is a pioneering technology company '
          'developing cryptocurrency trading platforms.\n\n**About The Role**\n\n'
          'Alldus is seeking a Staff Front End Engineer to join its team in New York.')
    result = resolve_employer('Netrolynx AI', jd, 'linkedin')
    assert result['hiring_employer'] is None
    assert result['relationship'] == 'unknown'
    assert result['agency_evidence'] in jd


@pytest.mark.parametrize('services', [
    'recruiting services', 'staffing solutions', 'talent acquisition services',
    'permanent placement services', 'recruitment and staffing services',
])
def test_candidate_own_about_services_override_role_claim(services):
    jd = (f'**About The Company**\n\nBridge Partners is a global provider of {services} '
          'for client technology businesses.\n\n**About The Role**\n\n'
          'Bridge Partners is seeking a frontend engineer to join its team.')
    result = resolve_employer('New Publisher', jd, 'linkedin')
    assert result['hiring_employer'] is None
    assert services in result['agency_evidence']


def test_recruiter_about_does_not_reject_named_product_client():
    jd = ('**About The Company**\n\nBridge Partners is a provider of talent acquisition services.'
          '\n\n**About The Role**\n\nAcme Labs is hiring a frontend engineer.')
    assert resolve_employer('New Publisher', jd, 'linkedin')['hiring_employer'] == 'Acme Labs'


@pytest.mark.parametrize('description', [
    'a platform building recruiting software for talent teams',
    'a software company providing staffing software solutions',
    'a developer tools company. We are recruiting engineers for our own team',
])
def test_product_company_about_is_not_recruiter(description):
    jd = (f'**About The Company**\n\nAcme Labs is {description}.'
          '\n\n**About The Role**\n\nAcme Labs is hiring a frontend engineer.')
    result = resolve_employer('New Publisher', jd, 'linkedin')
    assert result['hiring_employer'] == 'Acme Labs'
    assert result['agency_evidence'] is None


@pytest.mark.parametrize('publisher,description', [
    ('Greenhouse', 'building talent acquisition solutions for modern HR teams'),
    ('Workday', 'a software company selling talent acquisition solutions'),
    ('Acme Labs', 'building recruitment solutions for HR teams'),
    ('Acme Labs', 'a software platform for a recruitment company'),
    ('Acme Labs', 'a software vendor serving a staffing agency'),
])
def test_talent_product_copy_is_not_staffing_evidence(publisher, description):
    jd = (f'**About The Company**\n\n{publisher} is {description}.\n\n'
          f'**About The Role**\n\n{publisher} is hiring an engineer.')
    result = resolve_employer(publisher, jd, 'greenhouse')
    assert result['hiring_employer'] == publisher
    assert result['relationship'] == 'unchanged'
    assert result['agency_evidence'] is None


@pytest.mark.parametrize('publisher,jd', [
    ('Stripe', 'Stripe is hiring engineers to join a global company.'),
    ('Notion', 'Notion is looking for a designer to join a fast-growing company.'),
    ('Stripe', 'Stripe is hiring engineers for a global organization.'),
    ('Notion', 'We are hiring a designer to join a fast-growing company.'),
])
def test_generic_company_hiring_prose_is_direct(publisher, jd):
    result = resolve_employer(publisher, jd, 'greenhouse')
    assert result['hiring_employer'] == publisher
    assert result['relationship'] == 'unchanged'
    assert result['agency_evidence'] is None


@pytest.mark.parametrize('wording', [
    'our client', 'a client of ours', 'on behalf of a client',
    'on behalf of a prominent defense and security client',
])
def test_explicit_third_party_role_blocks_ats_fallback(wording):
    jd = f'Talent Bridge is hiring an engineer for {wording}.'
    result = resolve_employer('Talent Bridge', jd, 'greenhouse')
    assert result['hiring_employer'] is None
    assert result['agency_evidence'] == jd


def test_first_person_candidate_placement_is_not_staffing_evidence():
    jd = ('**About The Company**\n\nBridge Partners is a talent business. '
          'We place candidates with our clients.\n\n**About The Role**\n\n'
          'Bridge Partners is hiring an engineer.')
    result = resolve_employer('Bridge Partners', jd, 'greenhouse')
    assert result['hiring_employer'] == 'Bridge Partners'
    assert result['agency_evidence'] is None


@pytest.mark.parametrize('jd', [
    'We innovate on behalf of our customers.',
    'Our tools take automated actions on behalf of users.',
    'We deliver innovative digital platforms to our clients.',
])
def test_customer_service_copy_is_not_placement_evidence(jd):
    result = resolve_employer('New Publisher', jd, 'linkedin')
    assert result['hiring_employer'] is None
    assert result['agency_evidence'] is None


@pytest.mark.parametrize('jd', [
    'Our client is seeking an engineer.',
    'We are hiring engineers on behalf of our client.',
    '**About The Company**\nAcme Labs is a software company.\n'
    '**About The Role**\nOur client is seeking an engineer.',
])
def test_unnamed_third_party_statement_cannot_use_ats_or_blurb(jd):
    result = resolve_employer('New Publisher', jd, 'greenhouse')
    assert result['hiring_employer'] is None
    assert result['agency_evidence'] in jd


def test_talent_acquisition_firm_is_a_staffing_business():
    jd = '**About The Company**\nBridge Partners is a talent acquisition firm.'
    result = resolve_employer('Bridge Partners', jd, 'greenhouse')
    assert result['hiring_employer'] is None
    assert result['agency_evidence'] in jd
    assert 'talent acquisition firm' in result['agency_evidence']


@pytest.mark.parametrize('source', ['linkedin', 'greenhouse'])
@pytest.mark.parametrize('description', [
    'provides software for staffing services',
    'is a software vendor providing software for recruitment services',
    'provides staffing solutions software to HR teams',
])
def test_review_r3_software_vendor_keeps_own_employer(source, description):
    jd = (f'**About The Company**\nAcme Labs {description}.\n\n'
          '**About The Role**\nAcme Labs is hiring an engineer.')
    result = resolve_employer('Acme Labs', jd, source)
    assert result['hiring_employer'] == 'Acme Labs'
    assert result['agency_evidence'] is None


@pytest.mark.parametrize('organization', ['company', 'organization', 'firm', 'team'])
def test_review_r3_internal_recruitment_keeps_ats_fallback(organization):
    jd = f'Our internal recruitment team is hiring engineers on behalf of our {organization}.'
    result = resolve_employer('Acme Labs', jd, 'greenhouse')
    assert result['hiring_employer'] == 'Acme Labs'
    assert result['agency_evidence'] is None


@pytest.mark.parametrize('statement', [
    'We are a staffing firm.', 'We are a leading staffing firm.',
    'HireCo are a staffing agency.',
])
def test_review_r3_staffing_firm_self_description_is_agency(statement):
    result = resolve_employer('HireCo', statement, 'greenhouse')
    headed = statement.startswith('HireCo ')
    assert result['hiring_employer'] == (None if headed else 'HireCo')
    assert result['agency_evidence'] == (statement if headed else None)


@pytest.mark.parametrize('product', ['software', 'a platform', 'a tool', 'a SaaS', 'an app', 'a product'])
def test_service_provider_with_product_subject_is_not_agency(product):
    jd = (f'**About The Company**\nAcme Labs is {product} providing recruitment services.\n'
          '**About The Role**\nAcme Labs is hiring an engineer.')
    result = resolve_employer('Acme Labs', jd, 'greenhouse')
    assert result['hiring_employer'] == 'Acme Labs'
    assert result['agency_evidence'] is None


@pytest.mark.parametrize('description', [
    'a recruitment platform', 'staffing solutions software',
    'a provider of staffing solutions for HR teams',
])
def test_staffing_product_or_solutions_without_client_context_is_not_agency(description):
    jd = f'**About The Company**\nAcme Labs is {description}.'
    result = resolve_employer('Acme Labs', jd, 'greenhouse')
    assert result['hiring_employer'] == 'Acme Labs'
    assert result['agency_evidence'] is None


@pytest.mark.parametrize('client', [
    'our clients', 'a client', 'an unnamed client',
    'a leading technology company, our client', 'a partner company',
])
def test_client_wording_blocks_ats_fallback(client):
    jd = f'We are hiring engineers on behalf of {client}.'
    result = resolve_employer('HireCo', jd, 'greenhouse')
    assert result['hiring_employer'] is None
    assert result['agency_evidence'] == jd


@pytest.mark.parametrize('company', [
    'a company', 'a leading technology company',
    'a prominent, employee owned defense and security firm',
])
def test_on_behalf_of_company_requires_client_wording(company):
    jd = f'We are hiring engineers on behalf of {company}.'
    result = resolve_employer('Acme Labs', jd, 'greenhouse')
    assert result['hiring_employer'] == 'Acme Labs'
    assert result['agency_evidence'] is None


@pytest.mark.parametrize('employer,expected', [('HireCo', 'HireCo'), ('Acme Labs', 'Acme Labs')])
def test_first_person_staffing_description_distinguishes_publisher_from_client(employer, expected):
    jd = ('**About The Company**\nWe are a staffing firm.\n'
          f'**About The Role**\n{employer} is hiring an engineer.')
    result = resolve_employer('HireCo', jd, 'greenhouse')
    assert result['hiring_employer'] == expected
    assert result['agency_evidence'] is None


@pytest.mark.parametrize('source', ['linkedin', 'greenhouse'])
@pytest.mark.parametrize('jd', [
    'We build payroll software. Our customer is a recruitment agency.',
    'Our biggest customer is a staffing firm. We build accounting software.',
    'Our client is a recruitment agency. We build payroll software.',
    'Our clients include recruitment agencies and staffing firms.',
    'We help our clients automate payroll. Trusted by clients worldwide.',
    'Build client-facing tools with our team.',
    'We build impactful software solutions for our clients worldwide.',
    'Our client is a leading fintech company using our software.',
    '**About The Company**\nAcme Labs is a software company. Our customer is a staffing firm.\n'
    '**About The Role**\nAcme Labs is hiring engineers.',
])
def test_review_r4_customer_descriptions_are_not_publisher_agency_evidence(source, jd):
    result = resolve_employer('Acme Labs', jd, source)
    assert result['agency_evidence'] is None
    if source == 'greenhouse':
        assert result['hiring_employer'] == 'Acme Labs'


@pytest.mark.parametrize('source', ['linkedin', 'greenhouse'])
@pytest.mark.parametrize('statement', [
    'We are a recruiting firm.',
    'We are the leading recruitment consultancy.',
    'SoTalent is a recruiting firm.',
    'We are a talent agency.',
    'אנחנו חברת השמה.',
    'SoTalent היא חברת גיוס.',
])
def test_precision_self_description_labels_sotalent_without_inventing_client(source, statement):
    jd = f'**About The Company**\n{statement}\n**About The Role**\nSoTalent is hiring engineers.'
    result = resolve_employer('SoTalent', jd, source)
    named = statement.startswith('SoTalent ')
    assert result['agency_evidence'] == (statement if named else None)
    assert result['hiring_employer'] == (None if named else 'SoTalent')


@pytest.mark.parametrize('source', ['linkedin', 'greenhouse'])
@pytest.mark.parametrize('statement', [
    'Our client is hiring engineers.',
    'Our client is seeking an engineer.',
    'Our client is looking for engineers.',
    'We are hiring for one of our clients.',
    'Our recruitment firm represents a client.',
    'Direct employment with our client.',
])
def test_precision_explicit_client_hiring_is_agency_evidence(source, statement):
    result = resolve_employer('HireCo', statement, source)
    unattributed_self = statement.startswith('Our recruitment firm')
    assert result['agency_evidence'] == (None if unattributed_self else statement)
    assert result['hiring_employer'] == ('HireCo' if unattributed_self and source == 'greenhouse' else None)


def test_recruitment_word_in_product_company_name_is_not_agency_evidence():
    jd = ('**About The Company**\nAcme Recruitment Technologies is a software company.\n'
          '**About The Role**\nAcme Recruitment Technologies is hiring engineers.')
    result = resolve_employer('Acme Recruitment Technologies', jd, 'greenhouse')
    assert result['agency_evidence'] is None
    assert result['hiring_employer'] == 'Acme Recruitment Technologies'


R5_REMOVED = json.loads((Path(__file__).parents[1] /
                        'test_support/fixtures/employer_identity_r5_removed.json').read_text())


@pytest.mark.parametrize('row', R5_REMOVED, ids=lambda row: row['id'])
def test_review_r5_removed_publisher_badges(row):
    assert f"{row['company']} is a recruitment partner of this role." in row['raw_jd']
    result = resolve_employer(row['company'], row['raw_jd'], row['source'])
    assert result['agency_evidence'] is not None
    assert result['hiring_employer'] is None


@pytest.mark.parametrize('source', ['linkedin', 'greenhouse'])
@pytest.mark.parametrize('jd', [
    'We build payroll software for one of our clients.',
    'We build payroll software.\nHireCo is a staffing firm and our customer.',
])
def test_review_r5_customer_business_is_not_publisher_evidence(source, jd):
    result = resolve_employer('Acme Labs', jd, source)
    assert result['agency_evidence'] is None
    assert result['hiring_employer'] == ('Acme Labs' if source == 'greenhouse' else None)


@pytest.mark.parametrize('source', ['linkedin', 'greenhouse'])
@pytest.mark.parametrize('statement', [
    'HireCo is a recruitment partner of this role.',
    'We are a recruitment partner of this role.',
    'We are a recruiting firm.',
])
@pytest.mark.parametrize('padding', ['', 'Role responsibilities.\n' * 40, 'Role details. ' * 200 + '\n'])
def test_review_r6_publisher_self_description_anywhere(source, statement, padding):
    heading = 'About HireCo\n' if padding and statement.startswith('We ') else ''
    result = resolve_employer('HireCo', padding + heading + statement, source)
    unattributed_self = statement.startswith('We ')
    assert result['agency_evidence'] == (None if unattributed_self else statement)
    assert result['hiring_employer'] == ('HireCo' if unattributed_self and source == 'greenhouse' else None)


@pytest.mark.parametrize('statement', [
    'HireCo is a staffing firm and our customer.',
    'Our client is hiring an engineer.',
    'We are recruiting for one of our clients.',
])
def test_review_r6_late_customer_text_does_not_label_publisher(statement):
    jd = 'Role responsibilities.\n' * 40 + statement
    result = resolve_employer('Acme Labs', jd, 'greenhouse')
    assert result['agency_evidence'] is None
    assert result['hiring_employer'] == 'Acme Labs'


@pytest.mark.parametrize('predicate', ['hiring', 'seeking', 'looking for', 'recruiting'])
def test_review_r6_recruitment_for_one_client_needs_predicate(predicate):
    jd = f'We are {predicate} an engineer for one of our clients.'
    result = resolve_employer('HireCo', jd, 'greenhouse')
    assert result['agency_evidence'] == jd
    assert result['hiring_employer'] is None


@pytest.mark.parametrize('publisher', ['RemoteHunter', 'TalentHop'])
def test_review_r6_known_reposter_is_reviewed(publisher):
    from scraper.employer_identity import PUBLISHER_KEYS
    assert publisher.casefold() in PUBLISHER_KEYS
    assert resolve_employer(publisher, 'Build software.', 'greenhouse')['hiring_employer'] is None


def test_review_r6_on_behalf_of_one_client_is_representation():
    jd = 'We are acting on behalf of one of our clients.'
    result = resolve_employer('HireCo', jd, 'greenhouse')
    assert result['agency_evidence'] == jd
    assert result['hiring_employer'] is None


@pytest.mark.parametrize('source', ['linkedin', 'greenhouse'])
@pytest.mark.parametrize('footer', [
    'About XYZ Recruiting\nWe are a staffing firm.',
    'This posting is managed by XYZ Recruiting.\nAbout XYZ Recruiting\n'
    'We provide recruitment services to our clients.',
    'About HireCo: We are a staffing firm.',
    '**About HireCo**\nWe are a staffing firm.',
])
@pytest.mark.parametrize('padding', ['', 'Role responsibilities.\n' * 40])
def test_review_r7_other_company_first_person_is_not_publisher(source, footer, padding):
    jd = 'Acme Labs is hiring engineers.\n' + padding + footer
    result = resolve_employer('Acme Labs', jd, source)
    assert result['agency_evidence'] is None
    assert result['hiring_employer'] == 'Acme Labs'
    assert result['relationship'] == 'unchanged'


@pytest.mark.parametrize('source', ['linkedin', 'greenhouse'])
@pytest.mark.parametrize('heading', ['About HireCo:', 'About us:', '**About us**\n'])
def test_review_r7_publisher_late_first_person_is_conservative(source, heading):
    jd = 'Role responsibilities.\n' * 40 + heading + ' We are a recruitment agency.'
    result = resolve_employer('HireCo', jd, source)
    assert result['agency_evidence'] is None
    assert result['hiring_employer'] == ('HireCo' if source == 'greenhouse' else None)


@pytest.mark.parametrize('source', ['linkedin', 'greenhouse'])
def test_review_r7_unattributed_late_first_person_is_not_publisher(source):
    jd = 'Acme Labs is hiring engineers.\n' + 'Role responsibilities.\n' * 40
    result = resolve_employer('Acme Labs', jd + 'We are a staffing firm.', source)
    assert result['agency_evidence'] is None
    assert result['hiring_employer'] == 'Acme Labs'


@pytest.mark.parametrize('source', ['linkedin', 'greenhouse'])
def test_review_r7_named_publisher_statement_inside_other_section(source):
    jd = 'Role responsibilities.\n' * 40 + 'About OtherCo\nHireCo is a staffing firm.'
    result = resolve_employer('HireCo', jd, source)
    assert result['agency_evidence'] == 'HireCo is a staffing firm.'
    assert result['hiring_employer'] is None


@pytest.mark.parametrize('source', ['linkedin', 'greenhouse'])
@pytest.mark.parametrize('padding', ['', 'Role responsibilities.\n' * 40])
def test_review_r7_about_us_with_other_named_company_is_not_publisher(source, padding):
    jd = ('Acme Labs is hiring engineers.\n' + padding
          + 'About us:\nHireCo is a software company.\nWe are a recruitment agency.')
    result = resolve_employer('Acme Labs', jd, source)
    assert result['agency_evidence'] is None
    assert result['hiring_employer'] == 'Acme Labs'


@pytest.mark.parametrize('source', ['linkedin', 'greenhouse'])
def test_review_r7_opening_self_description_requires_owner_heading(source):
    result = resolve_employer('HireCo', 'We are a staffing firm.\nAbout OtherCo\nBuild tools.', source)
    assert result['agency_evidence'] is None
    assert result['hiring_employer'] == ('HireCo' if source == 'greenhouse' else None)


@pytest.mark.parametrize('source', ['linkedin', 'greenhouse'])
def test_review_r7_publisher_section_does_not_restore_first_person(source):
    jd = 'About OtherCo\nWe build tools.\n' + 'Role responsibilities.\n' * 40
    result = resolve_employer('HireCo', jd + 'About us:\nWe are a staffing firm.', source)
    assert result['agency_evidence'] is None
    assert result['hiring_employer'] == ('HireCo' if source == 'greenhouse' else None)


@pytest.mark.parametrize('source', ['linkedin', 'greenhouse'])
def test_review_r7_first_person_after_character_window_on_same_line(source):
    jd = 'Role details. ' * 200 + 'We are a staffing firm.'
    result = resolve_employer('Acme Labs', jd, source)
    assert result['agency_evidence'] is None
    assert result['hiring_employer'] == ('Acme Labs' if source == 'greenhouse' else None)


@pytest.mark.parametrize('source', ['linkedin', 'greenhouse'])
@pytest.mark.parametrize('section', [
    'About us:\n  HireCo is a staffing firm.\nWe are a staffing firm.',
    'About us:\nHireCo, our recruiting partner, introduces itself:\nWe are a staffing firm.',
    'About us\nHireCo helps employers find talent.\nWe are a staffing firm.',
    'אודות החברה\nHireCo is our recruiting partner.\nאנחנו חברת השמה.',
])
def test_review_r8_original_false_agency_probes(source, section):
    jd = 'Acme Labs is hiring engineers.\n'
    if not section.startswith('אודות'):
        jd += 'Role responsibilities.\n' * 40
    result = resolve_employer('Acme Labs', jd + section, source)
    assert result['agency_evidence'] is None
    assert result['hiring_employer'] == 'Acme Labs'
    assert result['relationship'] == 'unchanged'


@pytest.mark.parametrize('source', ['linkedin', 'greenhouse'])
@pytest.mark.parametrize('heading', ['About us', 'About Acme Labs', 'אודותינו'])
@pytest.mark.parametrize('other', [
    '  - Meet HireCo', 'Our partner HireCo', 'Trusted by Beta Labs',
    '  • היכרות עם טאלנטקו', 'השותפה שלנו חברת אופק', 'Our partner Build',
    'Ōura helps employers.', 'our partner hireco',
])
@pytest.mark.parametrize('position', ['before-heading', 'before-statement', 'after-statement'])
def test_review_r8_other_name_blocks_first_person(source, heading, other, position):
    lines = ['Acme Labs is hiring engineers.', heading, 'We are a staffing firm.']
    lines.insert({'before-heading': 1, 'before-statement': 2, 'after-statement': 3}[position], other)
    result = resolve_employer('Acme Labs', '\n'.join(lines), source)
    assert result['agency_evidence'] is None
    assert result['hiring_employer'] == 'Acme Labs'


@pytest.mark.parametrize('source', ['linkedin', 'greenhouse'])
@pytest.mark.parametrize('heading', [
    'About HireCo', 'About us', 'About the company', 'About company',
    'אודות החברה', 'אודותינו', 'אודות HireCo',
])
@pytest.mark.parametrize('statement', ['We are a staffing firm.', 'אנחנו חברת השמה.'])
def test_review_r8_clean_owner_heading_is_conservative(source, heading, statement):
    jd = 'Role responsibilities.\n' * 40 + heading + '\n' + statement
    result = resolve_employer('HireCo', jd, source)
    assert result['agency_evidence'] is None
    assert result['hiring_employer'] == ('HireCo' if source == 'greenhouse' else None)


@pytest.mark.parametrize('source', ['linkedin', 'greenhouse'])
@pytest.mark.parametrize('heading', ['', 'About the role\n'])
def test_review_r8_no_owner_heading_is_conservative(source, heading):
    jd = 'Acme Labs is hiring engineers.\n' + heading + 'We are a staffing firm.'
    result = resolve_employer('Acme Labs', jd, source)
    assert result['agency_evidence'] is None
    assert result['hiring_employer'] == 'Acme Labs'


@pytest.mark.parametrize('source', ['linkedin', 'greenhouse'])
@pytest.mark.parametrize('distance', [1, 2, 3, 4])
def test_review_r8_three_preceding_lines(source, distance):
    jd = ('HireCo introduces itself.\n' + '\n' * (distance - 1)
          + 'About us: We are a staffing firm.')
    result = resolve_employer('Acme Labs', jd, source)
    assert result['agency_evidence'] is None


@pytest.mark.parametrize('source', ['linkedin', 'greenhouse'])
def test_review_r8_publisher_alias_is_not_foreign(source):
    jd = 'About BMC\nBMC Software builds tools.\nWe are a staffing firm.'
    result = resolve_employer('BMC Software', jd, source)
    assert result['agency_evidence'] is None


@pytest.mark.parametrize('source', ['linkedin', 'greenhouse'])
def test_review_r8_third_person_survives_contaminated_section(source):
    jd = 'About OtherCo\nMeet HireCo\nAcme Labs is a staffing firm.'
    result = resolve_employer('Acme Labs', jd, source)
    assert result['agency_evidence'] == 'Acme Labs is a staffing firm.'
    assert result['hiring_employer'] is None


R9_FOREIGN_SIGNALS = [
    'our recruiting partner hireco introduces itself:',
    '- hireco is a staffing firm; it describes itself below:',
    '| partner | profile |\n| hireco | recruiting firm |',
    '[hireco](https://hireco.example) is our recruiting partner and introduces itself:',
    'in partnership with hireco worldwide.',
    'working with orbit recruiting on this role.',
    'posted via talentbridge for this opening.',
    'together with hireco we fill roles.',
    'email jobs@hireco.com',
]


@pytest.mark.parametrize('source', ['linkedin', 'greenhouse'])
@pytest.mark.parametrize('signal', R9_FOREIGN_SIGNALS)
def test_review_r9_lowercase_partner_sections_keep_publisher(source, signal):
    jd = 'Acme Labs is hiring engineers.\nAbout us\n' + signal + '\nWe are a staffing firm.'
    result = resolve_employer('Acme Labs', jd, source)
    assert result['agency_evidence'] is None
    assert result['hiring_employer'] == 'Acme Labs'
    assert result['relationship'] == 'unchanged'


@pytest.mark.parametrize('source', ['linkedin', 'greenhouse'])
@pytest.mark.parametrize('boundary', [
    '\n\n', '\nAbout us\n', '\nAbout the company\n', '\nאודות\n',
    '\n# Overview\n', '\nResponsibilities:\n', '\n---\n', '\n- Our business:\n',
])
def test_review_r9_first_person_after_section_break_is_not_publisher(source, boundary):
    jd = 'Acme Labs is hiring engineers.' + boundary + 'We are a staffing firm.'
    result = resolve_employer('Acme Labs', jd, source)
    assert result['agency_evidence'] is None
    assert result['hiring_employer'] == 'Acme Labs'


@pytest.mark.parametrize('source', ['linkedin', 'greenhouse'])
@pytest.mark.parametrize('statement', [
    'We are a staffing firm.', 'We are a recruiting firm.',
    'We provide recruitment services to our clients.', 'We place candidates.',
    'Our recruitment firm represents a client.', 'אנחנו חברת השמה.', 'אנו חברת גיוס.',
])
@pytest.mark.parametrize('prefix', ['', 'About us\n', 'Role details.\n' * 40 + 'אודות החברה\n'])
def test_review_r9_first_person_never_counts(source, statement, prefix):
    result = resolve_employer('Acme Labs', prefix + statement, source)
    assert result['agency_evidence'] is None
    assert result['hiring_employer'] == ('Acme Labs' if source == 'greenhouse' else None)


@pytest.mark.parametrize('source', ['linkedin', 'greenhouse'])
@pytest.mark.parametrize('statement', ['We are a staffing firm.', 'We provide recruitment services.'])
def test_review_r9_candidate_blurb_cannot_restore_first_person(source, statement):
    jd = ('**About The Company**\nAcme Labs is a technology business. ' + statement
          + '\n**About The Role**\nAcme Labs is hiring engineers.')
    result = resolve_employer('Acme Labs', jd, source)
    assert result['agency_evidence'] is None
    assert result['hiring_employer'] == 'Acme Labs'


@pytest.mark.parametrize('source', ['linkedin', 'greenhouse'])
@pytest.mark.parametrize('statement', [
    'I provide recruitment services.', 'I provide staffing services.',
    'I provide staffing solutions to our clients.',
    'You provide staffing services.', 'They provide recruitment services.',
    'He is a staffing firm.', 'She is a staffing firm.', 'It is a staffing firm.',
    'Company provides staffing services.', 'Agency provides recruitment services.',
    'HireCo provides recruitment services.',
])
def test_review_r10_blurb_staffing_subject_must_match_company(source, statement):
    jd = ('**About The Company**\nAcme Labs is a technology business. ' + statement
          + '\n**About The Role**\nAcme Labs is hiring engineers.')
    result = resolve_employer('Acme Labs', jd, source)
    assert result['agency_evidence'] is None
    assert result['hiring_employer'] == 'Acme Labs'


R10_QUOTED_CLIENT_TEXT = [
    '\"Our client is hiring engineers.\"',
    '“Our client is hiring engineers.”',
    '«Our client is hiring engineers.»',
    "'Our client is hiring engineers.'",
    '\"Our client is\nhiring engineers.\"',
    '> Our client is seeking a senior engineer.',
    '  > Our client, Orbit Inc, is hiring backend engineers.',
    'A candidate wrote: \"Our client, Beta Corp, is hiring.\"',
    '\"They are hiring on behalf of our client Nova.\"',
    'Customer testimonial:\n\"Our client is hiring engineers.\" — HireCo',
    'HireCo customer testimonial:\n\"We recruit on behalf of our clients using Acme Labs.\"',
    'A staffing customer says:\n\"We are hiring engineers for our clients using this software.\"',
    'Our client is hiring engineers. — Jane, Head of Talent',
    'Our client is hiring engineers. — jane smith, head of talent',
    'Our client is hiring engineers. — יעל כהן, מנהלת גיוס',
    'Review by Jane: Our client is hiring engineers.',
    "Jane’s review of Acme Labs: Our client is hiring engineers.",
    'In a review, Jane wrote: Our client is hiring engineers.',
    'Jane says our client is hiring engineers.',
    'Our client is hiring engineers, said Jane.',
    'Testimonial: Our client is hiring engineers.',
    'Customer review: Our client is hiring engineers.',
    'Testimonials\nOur client is hiring engineers.',
    '## Reviews\nOur client is hiring engineers.',
    '**What our customers say**\nOur client is hiring engineers.',
    'ממליצים\nOur client is hiring engineers.',
    'המלצות\nOur client is hiring engineers.',
    'Reviews:\nOur client, Orbit Inc, is hiring backend engineers.',
    'Testimonials\nAcme Labs is a staffing firm.',
    'Testimonials\n**Our client** is hiring engineers.',
    'Testimonials\n**Acme Labs** is a staffing firm.',
    'Testimonials\n**Our client is hiring engineers.**',
    'Testimonials\n## Customer stories\nOur client is hiring engineers.',
    'Testimonials\n## About our customers\nOur client is hiring engineers.',
    'Jane said: \"Customer story:\nOur client is hiring engineers.\"',
    '\"Acme Labs is a staffing firm.\"',
]


@pytest.mark.parametrize('source', ['linkedin', 'greenhouse'])
@pytest.mark.parametrize('quoted', R10_QUOTED_CLIENT_TEXT)
@pytest.mark.parametrize('hiring', ['', 'Acme Labs is hiring engineers.\n'])
def test_review_r10_quotes_and_testimonials_do_not_attribute_publisher(source, quoted, hiring):
    jd = hiring + 'About Acme Labs\nAcme Labs builds observability software.\n' + quoted
    result = resolve_employer('Acme Labs', jd, source)
    assert result['agency_evidence'] is None
    assert result['hiring_employer'] == ('Acme Labs' if hiring or source == 'greenhouse' else None)


@pytest.mark.parametrize('source', ['linkedin', 'greenhouse'])
@pytest.mark.parametrize('statement', [
    'Acme Labs provides staffing services.', 'acme labs provides staffing services.',
    'ACME LABS is a staffing firm.',
])
def test_review_r10_exact_publisher_name_is_case_insensitive(source, statement):
    result = resolve_employer('Acme Labs', statement, source)
    assert result['agency_evidence'] == statement
    assert result['hiring_employer'] is None


@pytest.mark.parametrize('source', ['linkedin', 'greenhouse'])
def test_review_r10_reviewed_alias_can_describe_publisher(source):
    result = resolve_employer('BMC Software', 'BMC provides staffing services.', source)
    assert result['agency_evidence'] == 'BMC provides staffing services.'
    assert result['hiring_employer'] is None


@pytest.mark.parametrize('source', ['linkedin', 'greenhouse'])
@pytest.mark.parametrize('heading', ['## About the role', '**About The Role**', 'Responsibilities:', 'Job Description', '**Job Description**'])
def test_review_r10_real_role_after_testimonials_is_still_attributed(source, heading):
    jd = ('Testimonials\nOur client is hiring engineers.\n' + heading
          + '\nOur client, Beta Corp, is hiring engineers.')
    result = resolve_employer('HireCo', jd, source)
    assert result['agency_evidence'] == 'Our client, Beta Corp, is hiring engineers.'
    assert result['hiring_employer'] == 'Beta Corp'


@pytest.mark.parametrize('source', ['linkedin', 'greenhouse'])
@pytest.mark.parametrize('row', json.loads((Path(__file__).parents[1] / 'test_support/fixtures/employer_identity_r10.json').read_text()), ids=lambda row: row['case'])
def test_review_r10_both_reviewers_reproducers(source, row):
    result = resolve_employer('Acme Labs', row['jd'], source)
    assert result['agency_evidence'] is None
    assert result['hiring_employer'] in {None, 'Acme Labs'}


@pytest.mark.parametrize('source', ['linkedin', 'greenhouse'])
@pytest.mark.parametrize('tail', [
    'You will participate in code reviews.',
    'Improve our customer reviews.', '— Remote', 'Review and debug timing paths.',
    'Guide design reviews and architecture discussions.',
    'Our values—Trust, Customer Obsession, Craftsmanship—guide the team.',
    'This is the employer — EngRadar is a job radar, not a recruiter.',
])
def test_review_r10_technical_reviews_and_prose_dashes_are_not_signatures(source, tail):
    jd = 'Acme Labs is hiring engineers. ' + tail
    result = resolve_employer('Acme Labs', jd, source)
    assert result['hiring_employer'] == 'Acme Labs'
    assert result['employer_evidence'] == jd
    assert result['agency_evidence'] is None


@pytest.mark.parametrize('source', ['linkedin', 'greenhouse'])
def test_review_r10_masking_preserves_original_crlf_evidence_offsets(source):
    jd = ('Customer testimonial:\r\n"Our client is hiring engineers."\r\n'
          '**About The Role**\r\nOur client, Beta Corp, is hiring engineers.')
    result = resolve_employer('HireCo', jd, source)
    assert result['hiring_employer'] == 'Beta Corp'
    assert result['employer_evidence'] in jd
    assert result['agency_evidence'] == 'Our client, Beta Corp, is hiring engineers.'


@pytest.mark.parametrize('publisher', ['I', 'We', 'You', 'They', 'He', 'She', 'It', 'Company', 'Agency', 'Firm', 'Recruiter', 'Team'])
def test_review_r10_pronoun_or_generic_publisher_is_not_a_staffing_subject(publisher):
    result = resolve_employer(publisher, publisher + ' provides staffing services.', 'linkedin')
    assert result['agency_evidence'] is None
