import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import httpx
import openai
from livekit.agents import APIConnectOptions, llm
from livekit.agents.voice.agent_session import SessionConnectOptions
from livekit.plugins.openai import LLM

from coach import JobCoach
from response_schemas import NaturalSpeech
from tools import Posting, SessionState
from user import User


class WriterCoach(JobCoach):
    def __init__(self, state, session):
        self.test_state = state
        self.test_session = session
        super().__init__(User.default())

    @property
    def state(self):
        return self.test_state

    @property
    def session(self):
        return self.test_session

    async def _audit_speech(self, text, facts):
        return None


class WriterJsonTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.requests = []
        self.reply = {}

        async def respond(request):
            self.requests.append((json.loads(request.content), request.extensions["timeout"]))
            chunk = {
                "id": "writer-response",
                "object": "chat.completion.chunk",
                "created": 0,
                "model": "qa-model",
                "choices": [{
                    "index": 0,
                    "delta": {"content": json.dumps(self.reply)},
                    "finish_reason": None,
                }],
            }
            return httpx.Response(
                200,
                headers={"Content-Type": "text/event-stream"},
                content=f"data: {json.dumps(chunk)}\n\ndata: [DONE]\n\n".encode(),
            )

        self.http = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        self.client = openai.AsyncClient(
            api_key="qa", base_url="http://qa.invalid/v1", http_client=self.http
        )
        self.model = LLM(model="qa-model", client=self.client)
        self.connect = APIConnectOptions(timeout=7.25, max_retry=0)
        session = SimpleNamespace(
            llm=self.model,
            conn_options=SessionConnectOptions(llm_conn_options=self.connect),
        )
        posting = Posting(
            uuid4(),
            "Backend Developer",
            "Acme",
            "Israel",
            82,
            "Python is listed.",
            "https://example.com/apply",
        )
        self.coach = WriterCoach(SessionState(turn_posting=posting), session)

    async def asyncTearDown(self):
        await self.model.aclose()
        await self.client.close()

    async def test_writer_sends_typed_schema_and_preserves_connection_options(self):
        self.reply = {
            "sentence": "I’d look closely at Backend Developer with Acme. It looks promising.",
            "stance": "recommend",
        }
        with patch.object(self.model, "chat", wraps=self.model.chat) as chat:
            output = [
                chunk
                async for chunk in self.coach.llm_node(
                    llm.ChatContext.empty(), [], None
                )
            ]

        self.assertEqual(
            output, ["I’d look closely at Backend Developer with Acme. It looks promising. "]
        )
        request, timeout = self.requests[0]
        response_format = request["response_format"]
        self.assertEqual(response_format["type"], "json_schema")
        self.assertEqual(response_format["json_schema"]["name"], NaturalSpeech.__name__)
        self.assertTrue(response_format["json_schema"]["strict"])
        schema = response_format["json_schema"]["schema"]
        self.assertEqual(set(schema["properties"]), {"sentence", "stance"})
        self.assertNotIn("$defs", schema)
        self.assertNotIn("tools", request)
        self.assertEqual(timeout, {key: 7.25 for key in ("connect", "read", "write", "pool")})
        self.assertIs(chat.call_args.kwargs["conn_options"], self.connect)

    async def test_writer_refuses_an_invented_url(self):
        self.reply = {
            "sentence": "Apply at https://invented.example/jobs/123.",
            "stance": "neutral",
        }
        with self.assertLogs("coach", "WARNING") as logs:
            output = [
                chunk
                async for chunk in self.coach.llm_node(
                    llm.ChatContext.empty(), [], None
                )
            ]
        self.assertNotIn("invented.example", " ".join(output).casefold())
        self.assertEqual(logs.records[0].reason, "unsupported_url")


if __name__ == "__main__":
    unittest.main()
