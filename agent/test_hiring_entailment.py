import asyncio
import json
import unittest
from types import SimpleNamespace

from claim_audit import GroundingError, audit_sentence
from response_schemas import AuditResponse


AUDIT = {"claims": [{"field": "company", "value": "Acme"}],
         "stance": "neutral", "unsupported": []}
TEXT = "Acme is currently hiring for this role."
FACTS = {"company": "Acme", "reasons": "Built MCP servers, aligning with the role requirements.",
         "user_profile": "Private candidate profile must not become a hiring premise."}


class Model:
    def __init__(self, replies, delays=()):
        self.replies, self.delays, self.requests, self.closed = iter(replies), iter(delays), [], 0

    def chat(self, **kwargs):
        self.requests.append(kwargs)
        content, delay, owner = json.dumps(next(self.replies)), next(self.delays, 0), self

        class Stream:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                owner.closed += 1

            def __aiter__(self):
                async def chunks():
                    await asyncio.sleep(delay)
                    yield SimpleNamespace(delta=SimpleNamespace(content=content))
                return chunks()

        return Stream()


def extraction(quote=FACTS["reasons"], field="reasons"):
    return {"asserted": True, "evidence": {"field": field, "quote": quote}}


class HiringEntailmentTests(unittest.IsolatedAsyncioTestCase):
    async def test_trace_quote_membership_alone_cannot_pass(self):
        model = Model([AUDIT, extraction(), {"entails": False}])
        with self.assertRaisesRegex(GroundingError, "hiring_without_evidence: not_entailed"):
            await audit_sentence(model, TEXT, FACTS)
        self.assertEqual(len(model.requests), 3)
        data = [json.loads(r["chat_ctx"].messages()[-1].text_content) for r in model.requests]
        self.assertNotIn("user_profile", data[1]["premises"])
        self.assertEqual(data[2], {"sentence": TEXT, "identity": {"company": "Acme"},
                                   "evidence": FACTS["reasons"]})
        self.assertNotIn("asserted", data[2])
        self.assertEqual(model.closed, 3)
        for request in model.requests:
            self.assertEqual(request["conn_options"].max_retry, 0)

    async def test_actual_hiring_evidence_has_independent_positive_control(self):
        model = Model([AUDIT, extraction(TEXT), {"entails": True}])
        await audit_sentence(model, TEXT, {**FACTS, "reasons": TEXT})
        self.assertEqual(len(model.requests), 3)

    async def test_non_hiring_identity_skips_entailment(self):
        model = Model([AUDIT, {"asserted": False, "evidence": None}])
        await audit_sentence(model, "Acme is the company.", FACTS)
        self.assertEqual(len(model.requests), 2)

    async def test_missing_or_foreign_evidence_never_reaches_entailment(self):
        for decision in (extraction("invented"), extraction(""), extraction(field="user_profile"),
                         {"asserted": True, "evidence": None},
                         {"asserted": False, "evidence": extraction()["evidence"]},
                         {"asserted": "false", "evidence": None}):
            with self.subTest(decision=decision):
                model = Model([AUDIT, decision])
                with self.assertRaises(GroundingError):
                    await audit_sentence(model, TEXT, FACTS)
                self.assertEqual(len(model.requests), 2)

    async def test_non_boolean_entailment_fails_closed(self):
        model = Model([AUDIT, extraction(), {"entails": "true"}])
        with self.assertRaisesRegex(GroundingError, "invalid_hiring_evidence"):
            await audit_sentence(model, TEXT, FACTS)

    async def test_freshness_refusal_precedes_the_new_gate(self):
        model = Model([{**AUDIT, "unsupported": ["opened today is not evidenced"]}])
        with self.assertRaisesRegex(GroundingError, "unsupported_proposition"):
            await audit_sentence(model, "Acme opened today and is still hiring.", FACTS)
        self.assertEqual(len(model.requests), 1)
        self.assertEqual(set(AuditResponse.model_fields), {"claims", "stance", "unsupported"})

    async def test_all_legs_share_original_deadline_and_close_active_stream(self):
        model = Model([AUDIT, extraction(), {"entails": True}], delays=(0.03, 0.03, 0.08))
        with self.assertRaises(TimeoutError):
            await audit_sentence(model, TEXT, FACTS, timeout=0.1)
        self.assertEqual(len(model.requests), 3)
        self.assertEqual(model.closed, 3)
