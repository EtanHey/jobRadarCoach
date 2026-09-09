import asyncio
import json
import unittest
from types import SimpleNamespace

from claim_audit import GroundingError, audit_sentence, validate_audit

FACTS = {"company": "Acme", "title": "Developer", "location": "Israel", "score": "82", "apply_url": "https://example.com/apply"}


class AuditTests(unittest.TestCase):
    def test_extracted_values_must_match_current_posting(self):
        for field, value in (("company", "Stripe"), ("title", "CEO"), ("location", "London"), ("score", "91"), ("apply_url", "https://invented.example")):
            with self.subTest(field=field), self.assertRaises(GroundingError):
                validate_audit({"claims": [{"field": field, "value": value}], "stance": "neutral", "unsupported": []}, FACTS)

    def test_actual_recommendation_cannot_hide_behind_writer_neutral_label(self):
        with self.assertRaisesRegex(GroundingError, "spoken_stance"):
            validate_audit({"claims": [], "stance": "recommend", "unsupported": []}, {**FACTS, "score": "35"})

    def test_invalid_score_returns_a_stable_grounding_failure(self):
        for score in ("", "82.5", "unknown", "101", "-1"):
            with self.subTest(score=score), self.assertRaisesRegex(GroundingError, "invalid_verified_score"):
                validate_audit({"claims": [], "stance": "neutral", "unsupported": []}, {**FACTS, "score": score})

    def test_unsupported_propositions_and_malformed_audits_fail(self):
        for audit in ({}, {"claims": [], "stance": "neutral", "unsupported": ["Team growth was invented"]}, {"claims": [], "stance": "neutral", "unsupported": False}):
            with self.subTest(audit=audit), self.assertRaises(GroundingError):
                validate_audit(audit, FACTS)

    def test_natural_conversation_and_verified_identity_pass(self):
        validate_audit({"claims": [], "stance": "neutral", "unsupported": []}, {})
        validate_audit({"claims": [{"field": "company", "value": "Acme"}], "stance": "recommend", "unsupported": []}, FACTS)


class AuditStreamTests(unittest.IsolatedAsyncioTestCase):
    async def test_timeout_closes_auditor_and_uses_only_current_facts(self):
        closed = asyncio.Event()
        contexts = []

        class Stream:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                closed.set()

            def __aiter__(self):
                return self

            async def __anext__(self):
                await asyncio.Event().wait()

        def chat(**kwargs):
            contexts.append(kwargs["chat_ctx"])
            return Stream()

        with self.assertRaises(TimeoutError):
            await audit_sentence(SimpleNamespace(chat=chat), "Stripe would suit you", FACTS, timeout=0.01)
        self.assertTrue(closed.is_set())
        request = json.loads(contexts[0].messages()[-1].text_content)
        self.assertEqual(request, {"facts": FACTS, "sentence": "Stripe would suit you"})


if __name__ == "__main__":
    unittest.main()
