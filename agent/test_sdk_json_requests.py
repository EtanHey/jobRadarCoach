"""Exercise real LiveKit/OpenAI adapters, replacing only HTTP transport."""
import json
import unittest
from types import SimpleNamespace

import httpx
import openai
from livekit.plugins.openai import LLM

from claim_audit import GroundingError, audit_sentence
from coach import JobCoach


class SdkJsonRequests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.requests = []
        self.reply = {}

        async def respond(request):
            self.requests.append(json.loads(request.content))
            chunk = {
                "id": "qa-response", "object": "chat.completion.chunk", "created": 0,
                "model": "qa-model", "choices": [{
                    "index": 0, "delta": {"content": json.dumps(self.reply)},
                    "finish_reason": None,
                }],
            }
            return httpx.Response(200, headers={"Content-Type": "text/event-stream"},
                                  content=f"data: {json.dumps(chunk)}\n\ndata: [DONE]\n\n".encode())

        self.http = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        self.client = openai.AsyncClient(api_key="qa", base_url="http://qa.invalid/v1", http_client=self.http)
        self.model = LLM(model="qa-model", client=self.client)

    async def asyncTearDown(self):
        await self.model.aclose()
        await self.client.close()

    async def test_intent_json_mode_reaches_provider_and_is_validated(self):
        self.reply = {"action": "discuss", "filters": {}, "more_options": False}
        coach = SimpleNamespace(state=SimpleNamespace(current_posting=None),
                                session=SimpleNamespace(llm=self.model))
        intent = await JobCoach._resolve_intent(coach, "Could you explain the tradeoffs?")
        self.assertIsNotNone(intent)
        self.assertEqual(intent.action, "discuss")
        self.assertEqual(self.requests[0]["response_format"], {"type": "json_object"})

    async def test_audit_json_mode_reaches_provider_and_rejects_invented_claim(self):
        self.reply = {"claims": [{"field": "company", "value": "Acme"}],
                      "stance": "neutral", "unsupported": []}
        await audit_sentence(self.model, "Acme is the company.", {"company": "Acme"},
                             expected_references=("company",))
        self.assertEqual(self.requests[0]["response_format"]["type"], "json_schema")
        self.assertTrue(self.requests[0]["response_format"]["json_schema"]["strict"])
        self.reply["claims"][0]["value"] = "Invented"
        with self.assertRaisesRegex(GroundingError, "claim_mismatch"):
            await audit_sentence(self.model, "Invented is the company.", {"company": "Acme"})
        self.assertEqual(len(self.requests), 2)


if __name__ == "__main__":
    unittest.main()
