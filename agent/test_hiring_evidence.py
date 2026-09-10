"""Hiring assertions require an explicit decision and source-bound evidence."""
import unittest

from claim_audit import GroundingError, validate_audit
from response_schemas import AuditResponse

FACTS = {'company': 'Acme', 'title': 'ML Engineer', 'score': '82',
         'reasons': 'You have built MCP servers and memory systems.'}
BASE = {'claims': [], 'stance': 'neutral', 'unsupported': [],
        'hiring_assertion': {'asserted': False, 'evidence': None}}


class HiringEvidenceTests(unittest.TestCase):
    def test_explicit_hiring_reason_and_outcome_are_valid_provenance(self):
        quote = 'The selected team confirms that recruitment remains active.'
        for field in ('reasons', 'outcome'):
            with self.subTest(field=field):
                payload = {**BASE, 'hiring_assertion': {
                    'asserted': True, 'evidence': {'field': field, 'quote': quote}}}
                validate_audit(payload, {**FACTS, field: quote}, 'They are recruiting for this role.')

    def test_asserted_hiring_without_evidence_is_rejected(self):
        payload = {**BASE, 'hiring_assertion': {'asserted': True, 'evidence': None}}
        with self.assertRaisesRegex(GroundingError, '^hiring_without_evidence'):
            validate_audit(payload, FACTS, 'They are recruiting for this role.')

    def test_identity_and_user_profile_cannot_establish_hiring(self):
        for field, quote in (('company', 'Acme'), ('title', 'ML Engineer'), ('user_profile', 'Recruitment')):
            with self.subTest(field=field), self.assertRaisesRegex(GroundingError, '^hiring_without_evidence'):
                validate_audit({**BASE, 'hiring_assertion': {
                    'asserted': True, 'evidence': {'field': field, 'quote': quote}}},
                    {**FACTS, 'user_profile': 'Recruitment'}, 'They are recruiting for this role.')

    def test_empty_or_fabricated_quote_is_not_evidence(self):
        for quote in ('', '   ', 'The selected team is actively recruiting.'):
            with self.subTest(quote=quote), self.assertRaisesRegex(GroundingError, '^hiring_without_evidence'):
                validate_audit({**BASE, 'hiring_assertion': {
                    'asserted': True, 'evidence': {'field': 'reasons', 'quote': quote}}},
                    FACTS, 'They are recruiting for this role.')

    def test_nonassertion_stays_valid_without_hiring_evidence(self):
        validate_audit(BASE, FACTS, 'The recorded role looks interesting.')

    def test_missing_and_malformed_decision_fail_closed(self):
        missing = {key: value for key, value in BASE.items() if key != 'hiring_assertion'}
        with self.assertRaises(GroundingError):
            validate_audit(missing, FACTS, 'They are recruiting.')
        for decision in (None, {}, {'asserted': 'false', 'evidence': None},
                         {'asserted': False, 'evidence': {'field': 'reasons', 'quote': FACTS['reasons']}}):
            with self.subTest(decision=decision), self.assertRaisesRegex(GroundingError, '^invalid_hiring_assertion'):
                validate_audit({**BASE, 'hiring_assertion': decision}, FACTS, 'The recorded role looks interesting.')

    def test_provider_schema_requires_explicit_hiring_decision(self):
        schema = AuditResponse.model_json_schema()
        self.assertIn('hiring_assertion', schema['required'])
