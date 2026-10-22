"""Pure-Python grammar and SQL-generation checks; no services or subprocesses."""

import hashlib
import json
import unittest

from scripts.generate_years_metadata import COLLECTIVE_FRAME, COMPLETE_FRAME, FRAME, ROOT, SPEC, experience_phrase, generate, sql_regex


class YearsPrecisionTests(unittest.TestCase):
    def test_synthetic_quotes(self):
        cases = json.loads((ROOT / 'ui/tests/fixtures/years-extraction.json').read_text())
        for description, expected in cases:
            with self.subTest(description=description):
                actual = experience_phrase(description)
                self.assertEqual(actual, expected)
                if actual is not None:
                    self.assertIn(actual, description)

    def test_sql_uses_shared_grammar_and_preserves_contract(self):
        sql = (ROOT / 'supabase/migrations/0041_years_employer_tenure.sql').read_text()
        self.assertEqual(sql, generate())
        for key in ('complexity', 'optionalScope', 'requiredHeading', 'requiredContext',
                    'company', 'tenure', 'extraNumber', 'fractionalTenure', 'numberedTenure',
                    'inlineRequiredHeading', 'quantity', 'preference', 'domainPreference',
                    'numericTenure', 'domainContext', 'role', 'alternativeNumber',
                    'employerVerb', 'applicantVerb', 'precedingNumber', 'decade',
                    'yoeAnnotation', 'collectiveTenure', 'interruptedPreferencePrefix',
                    'exclusionQuantity'):
            self.assertIn(sql_regex(SPEC[key]), sql, key)
        self.assertIn(sql_regex(FRAME), sql)
        self.assertIn(sql_regex(COMPLETE_FRAME), sql)
        self.assertIn(sql_regex(COLLECTIVE_FRAME), sql)
        self.assertIn(sql_regex(SPEC['normalization']['joinTenure']), sql)
        for frame in SPEC['simple']:
            self.assertIn(sql_regex(frame), sql)
        for key in ('space', 'newline'):
            self.assertIn(' || '.join(f'chr({ord(c)})' for c in SPEC['normalization'][key]), sql)
        self.assertIn('immutable security invoker set search_path =', sql)
        self.assertIn('revoke all on function public.posting_list_metadata(text) from public, anon, authenticated;', sql)
        self.assertIn('grant execute on function public.posting_list_metadata(text) to service_role;', sql)
        self.assertNotIn('alter table', sql.lower())
        self.assertNotIn('update public.', sql.lower())

    def test_applied_migrations_are_immutable(self):
        for name, expected in (
            ('0039_years_metadata.sql', '7737a907602990f83bb4a4a436cf8e96fb76a767982549cb736a9d3fa16b6f87'),
            ('0040_years_compact_formats.sql', '7f4792fbdf446b22a6cf464c543aefbd1950fe65990c6e06390d560b097c788a'),
        ):
            with self.subTest(migration=name):
                self.assertEqual(hashlib.sha256((ROOT / 'supabase/migrations' / name).read_bytes()).hexdigest(), expected)


if __name__ == '__main__':
    unittest.main()
