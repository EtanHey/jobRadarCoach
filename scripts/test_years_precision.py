"""Pure-Python grammar and SQL-generation checks; no services or subprocesses."""

import json
import unittest

from scripts.generate_years_metadata import FRAME, ROOT, SPEC, experience_phrase, generate, sql_regex


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
        sql = (ROOT / 'supabase/migrations/0039_years_metadata.sql').read_text()
        self.assertEqual(sql, generate())
        for key in ('complexity', 'optionalScope', 'requiredHeading', 'requiredContext',
                    'company', 'tenure', 'extraNumber', 'fractionalTenure', 'numberedTenure',
                    'inlineRequiredHeading', 'quantity'):
            self.assertIn(sql_regex(SPEC[key]), sql, key)
        self.assertIn(sql_regex(FRAME), sql)
        for key in ('space', 'newline'):
            self.assertIn(' || '.join(f'chr({ord(c)})' for c in SPEC['normalization'][key]), sql)
        self.assertIn('immutable security invoker set search_path =', sql)
        self.assertIn('revoke all on function public.posting_list_metadata(text) from public, anon, authenticated;', sql)
        self.assertIn('grant execute on function public.posting_list_metadata(text) to service_role;', sql)
        self.assertNotIn('alter table', sql.lower())
        self.assertNotIn('update public.', sql.lower())


if __name__ == '__main__':
    unittest.main()
