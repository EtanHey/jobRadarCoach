"""Exercise real LiveKit/OpenAI adapters, replacing only HTTP transport."""
import json
import os
import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import openai
from livekit.agents import APIConnectionError, Agent, AgentSession, llm
from livekit.plugins.openai import LLM

from claim_audit import GroundingError, audit_sentence
from coach import JobCoach
from main import llm_session_connect_options


class SdkJsonRequests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.requests = []
        self.reply = {}
        self.replies = None
        self.response_delays = []

        async def respond(request):
            self.requests.append(json.loads(request.content))
            request_index = len(self.requests) - 1
            if request_index < len(self.response_delays):
                await asyncio.sleep(self.response_delays[request_index])
            reply = self.replies[request_index] if self.replies is not None else self.reply
            chunk = {
                "id": "qa-response", "object": "chat.completion.chunk", "created": 0,
                "model": "qa-model", "choices": [{
                    "index": 0, "delta": {"content": json.dumps(reply)},
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

    async def test_conflicting_remote_preference_is_repaired_as_search(self):
        self.replies = [
            {"action": "discuss", "filters": {"remote": True}, "more_options": False},
            {"action": "search", "filters": {"remote": True}, "more_options": False},
        ]
        coach = SimpleNamespace(state=SimpleNamespace(current_posting=None),
                                session=SimpleNamespace(llm=self.model))
        intent = await JobCoach._resolve_intent(coach, "I prefer remote roles")
        self.assertEqual(intent.action, "search")
        self.assertEqual(intent.filters, {"remote": True})
        self.assertEqual(len(self.requests), 2)
        repair_messages = self.requests[1]["messages"]
        self.assertEqual(repair_messages[1], {"role": "user", "content": "I prefer remote roles"})
        self.assertEqual(repair_messages[-2]["role"], "assistant")
        self.assertIn("action/filter conflict", repair_messages[-1]["content"])
        self.assertNotIn("job", json.dumps(repair_messages[-1]).casefold())

    async def test_malformed_conflicts_fail_without_repair_request(self):
        cases = (
            (
                {"action": "discuss", "filters": {"remote": "yes"}, "more_options": False},
                "I prefer remote roles",
            ),
            (
                {"action": "discuss", "filters": {"location": "Israel"}, "more_options": False},
                "Could you explain the tradeoffs?",
            ),
            (
                {"action": "discuss", "filters": {"remote": True}, "more_options": True},
                "I prefer remote roles",
            ),
        )
        coach = SimpleNamespace(state=SimpleNamespace(current_posting=None),
                                session=SimpleNamespace(llm=self.model))
        for reply, utterance in cases:
            with self.subTest(reply=reply):
                self.reply = reply
                self.requests.clear()
                self.assertIsNone(await JobCoach._resolve_intent(coach, utterance))
                self.assertEqual(len(self.requests), 1)

    async def test_conflicting_discussion_is_repaired_without_filters(self):
        self.replies = [
            {"action": "discuss", "filters": {"remote": True}, "more_options": False},
            {"action": "discuss", "filters": {}, "more_options": False},
        ]
        coach = SimpleNamespace(state=SimpleNamespace(current_posting=object()),
                                session=SimpleNamespace(llm=self.model))
        intent = await JobCoach._resolve_intent(coach, "Would remote work be good for me?")
        self.assertEqual(intent.action, "discuss")
        self.assertEqual(intent.filters, {})
        self.assertEqual(len(self.requests), 2)

    async def test_repaired_invented_filter_is_rejected(self):
        self.replies = [
            {"action": "discuss", "filters": {"remote": True}, "more_options": False},
            {"action": "search", "filters": {"location": "Israel"}, "more_options": False},
        ]
        coach = SimpleNamespace(state=SimpleNamespace(current_posting=None),
                                session=SimpleNamespace(llm=self.model))
        self.assertIsNone(await JobCoach._resolve_intent(coach, "I prefer remote roles"))
        self.assertEqual(len(self.requests), 2)

    async def test_second_action_conflict_stops_after_two_attempts(self):
        self.replies = [
            {"action": "discuss", "filters": {"remote": True}, "more_options": False},
            {"action": "next", "filters": {"remote": True}, "more_options": False},
        ]
        coach = SimpleNamespace(state=SimpleNamespace(current_posting=None),
                                session=SimpleNamespace(llm=self.model))
        self.assertIsNone(await JobCoach._resolve_intent(coach, "I prefer remote roles"))
        self.assertEqual(len(self.requests), 2)

    async def test_other_invalid_fields_do_not_retry(self):
        self.reply = {"action": "search", "filters": {}, "more_options": False, "extra": True}
        coach = SimpleNamespace(state=SimpleNamespace(current_posting=None),
                                session=SimpleNamespace(llm=self.model))
        self.assertIsNone(await JobCoach._resolve_intent(coach, "I prefer remote roles"))
        self.assertEqual(len(self.requests), 1)

    async def test_repair_shares_the_original_deadline(self):
        self.replies = [
            {"action": "discuss", "filters": {"remote": True}, "more_options": False},
            {"action": "search", "filters": {"remote": True}, "more_options": False},
        ]
        self.response_delays = [0.02, 0.09]
        coach = SimpleNamespace(state=SimpleNamespace(current_posting=None),
                                session=SimpleNamespace(llm=self.model))
        with patch("coach.INTENT_TIMEOUT_SECONDS", 0.1), self.assertLogs("coach", "WARNING") as logs:
            intent = await JobCoach._resolve_intent(coach, "I prefer remote roles")
        self.assertIsNone(intent)
        self.assertEqual(len(self.requests), 2)
        self.assertEqual(logs.records[0].reason, "intent_timeout")

    async def test_audit_json_mode_reaches_provider_and_rejects_invented_claim(self):
        self.reply = {"claims": [{"field": "company", "value": "Acme"}],
                      "stance": "neutral", "unsupported": [], "hiring_assertion": {"asserted": False, "evidence": None}}
        await audit_sentence(self.model, "Acme is the company.", {"company": "Acme"})
        self.assertEqual(self.requests[0]["response_format"]["type"], "json_schema")
        self.assertTrue(self.requests[0]["response_format"]["json_schema"]["strict"])
        self.reply["claims"][0]["value"] = "Invented"
        with self.assertRaisesRegex(GroundingError, "claim_mismatch"):
            await audit_sentence(self.model, "Invented is the company.", {"company": "Acme"})
        self.assertEqual(len(self.requests), 2)


class LlmConnectionBudgetTests(unittest.IsolatedAsyncioTestCase):
    async def test_default_llm_node_uses_configured_timeout_and_retry_budget(self):
        attempts = []

        async def respond(request):
            if request.url.path.endswith("/models"):
                return httpx.Response(200, json={"object": "list", "data": []})
            attempts.append(request.extensions["timeout"])
            if len(attempts) <= 2:
                raise httpx.ConnectError("synthetic outage", request=request)
            chunk = {
                "id": "qa-response",
                "object": "chat.completion.chunk",
                "created": 0,
                "model": "qa-model",
                "choices": [{"index": 0, "delta": {"content": "ok"}, "finish_reason": None}],
            }
            return httpx.Response(
                200,
                headers={"Content-Type": "text/event-stream"},
                content=f"data: {json.dumps(chunk)}\n\ndata: [DONE]\n\n".encode(),
            )

        http = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        client = openai.AsyncClient(
            api_key="qa",
            base_url="http://qa.invalid/v1",
            http_client=http,
            max_retries=0,
        )
        model = LLM(model="qa-model", client=client)
        with patch.dict(
            os.environ,
            {"LLM_TIMEOUT": "7.5", "LLM_HTTP_RETRIES": "1"},
        ):
            session = AgentSession(
                llm=model,
                conn_options=llm_session_connect_options(),
            )

        class SyntheticAgent(Agent):
            def _get_activity_or_raise(self):
                return SimpleNamespace(llm=model, session=session)

        agent = SyntheticAgent(instructions="test")
        sleep = AsyncMock()
        try:
            with patch("livekit.agents.llm.llm.asyncio.sleep", sleep):
                with self.assertRaises(APIConnectionError):
                    async for _chunk in Agent.default.llm_node(
                        agent, llm.ChatContext.empty(), [], None
                    ):
                        pass
        finally:
            await model.aclose()
            await client.close()

        self.assertEqual(len(attempts), 2)
        self.assertEqual(
            attempts,
            [{"connect": 7.5, "read": 7.5, "write": 7.5, "pool": 7.5}] * 2,
        )
        sleep.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
