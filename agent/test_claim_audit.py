import asyncio
import json
import unittest
from types import SimpleNamespace

from claim_audit import GroundingError, audit_sentence, validate_audit

FACTS = {"company": "Acme", "title": "Developer", "location": "Israel", "score": "82", "apply_url": "https://example.com/apply"}
EMPTY_AUDIT = {"claims": [], "stance": "neutral", "unsupported": []}


def audit_model(payload):
    encoded = json.dumps(payload)

    class Stream:
        def __init__(self):
            self.chunks = iter((encoded[:20], encoded[20:]))

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            pass

        def __aiter__(self):
            return self

        async def __anext__(self):
            try:
                content = next(self.chunks)
            except StopIteration:
                raise StopAsyncIteration
            return SimpleNamespace(delta=SimpleNamespace(content=content))

    return SimpleNamespace(chat=lambda **_kwargs: Stream())


class AuditTests(unittest.TestCase):
    def test_empty_or_partial_audit_cannot_omit_spoken_identity(self):
        cases = (
            ("Acme looks strong.", [], "company"),
            (
                "Acme's Developer role in Israel looks strong.",
                [{"field": "company", "value": "Acme"}],
                "title|location",
            ),
            ("It scored 82.", [], "score"),
            ("Apply at https://example.com/apply.", [], "apply_url"),
        )
        for text, claims, missing in cases:
            with self.subTest(text=text), self.assertRaisesRegex(
                GroundingError, "audit_omitted_spoken_identity"
            ) as raised:
                validate_audit({**EMPTY_AUDIT, "claims": claims}, FACTS, text)
            for field in missing.split("|"):
                self.assertIn(field, str(raised.exception))

    def test_short_identity_names_use_token_boundaries(self):
        for company in ("AI", "X", "Go"):
            with self.subTest(company=company), self.assertRaisesRegex(
                GroundingError, "audit_omitted_spoken_identity"
            ):
                validate_audit(EMPTY_AUDIT, {**FACTS, "company": company}, f"{company} looks strong.")
        validate_audit(EMPTY_AUDIT, {**FACTS, "company": "AI"}, "I said that already.")
        validate_audit(EMPTY_AUDIT, {**FACTS, "company": "Go"}, "That sounds good.")

    def test_identity_and_url_digits_do_not_imply_score(self):
        facts = {
            **FACTS,
            "company": "Studio 54",
            "title": "Engineer Level 54",
            "location": "District 54",
            "score": "54",
        }
        for text, claim in (
            ("Studio 54 looks interesting.", {"field": "company", "value": "Studio 54"}),
            ("Engineer Level 54 looks interesting.", {"field": "title", "value": "Engineer Level 54"}),
            ("District 54 could work.", {"field": "location", "value": "District 54"}),
            ("Use https://example.com/apply/54.", {"field": "apply_url", "value": "https://example.com/apply/54"}),
        ):
            case_facts = (
                {**facts, "apply_url": "https://example.com/apply/54"}
                if claim["field"] == "apply_url"
                else facts
            )
            with self.subTest(text=text):
                validate_audit({**EMPTY_AUDIT, "claims": [claim]}, case_facts, text)

        with self.assertRaisesRegex(GroundingError, "score"):
            validate_audit(
                {**EMPTY_AUDIT, "claims": [{"field": "company", "value": "Studio 54"}]},
                facts,
                "Studio 54 scored 54.",
            )

    def test_claim_free_words_and_repeated_valid_identity_pass(self):
        for text in ("Absolutely, I see why that bothers you.", "How does that sound?"):
            validate_audit(EMPTY_AUDIT, FACTS, text)
        validate_audit(
            {**EMPTY_AUDIT, "claims": [{"field": "company", "value": "Acme"}]},
            FACTS,
            "Acme could fit. Acme is worth discussing.",
        )

    def test_extracted_values_must_match_current_posting(self):
        for field, value in (("company", "Stripe"), ("title", "CEO"), ("location", "London"), ("score", "91"), ("apply_url", "https://invented.example")):
            with self.subTest(field=field), self.assertRaises(GroundingError):
                validate_audit({"claims": [{"field": field, "value": value}], "stance": "neutral", "unsupported": []}, FACTS, "Stripe would suit you.")

    def test_actual_recommendation_cannot_hide_behind_writer_neutral_label(self):
        with self.assertRaisesRegex(GroundingError, "spoken_stance"):
            validate_audit({"claims": [], "stance": "recommend", "unsupported": []}, {**FACTS, "score": "35"}, "Apply now.")

    def test_invalid_score_returns_a_stable_grounding_failure(self):
        for score in ("", "82.5", "unknown", "101", "-1"):
            with self.subTest(score=score), self.assertRaisesRegex(GroundingError, "invalid_verified_score"):
                validate_audit({"claims": [], "stance": "neutral", "unsupported": []}, {**FACTS, "score": score}, "Let's discuss it.")

    def test_unsupported_propositions_and_malformed_audits_fail(self):
        for audit in ({}, {"claims": [], "stance": "neutral", "unsupported": ["Team growth was invented"]}, {"claims": [], "stance": "neutral", "unsupported": False}):
            with self.subTest(audit=audit), self.assertRaises(GroundingError):
                validate_audit(audit, FACTS, "Let's discuss it.")

    def test_natural_conversation_and_verified_identity_pass(self):
        validate_audit(EMPTY_AUDIT, {}, "Absolutely.")
        validate_audit({"claims": [{"field": "company", "value": "Acme"}], "stance": "recommend", "unsupported": []}, FACTS, "Acme looks strong.")


class AuditStreamTests(unittest.IsolatedAsyncioTestCase):
    async def test_empty_model_audit_is_rejected_using_spoken_text(self):
        with self.assertRaisesRegex(GroundingError, "audit_omitted_spoken_identity"):
            await audit_sentence(audit_model(EMPTY_AUDIT), "Acme looks strong.", FACTS)

    async def test_fragmented_matching_model_audit_passes(self):
        payload = {
            **EMPTY_AUDIT,
            "claims": [{"field": "company", "value": "Acme"}],
            "stance": "recommend",
        }
        await audit_sentence(audit_model(payload), "Acme looks strong.", FACTS)

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
