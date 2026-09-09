import asyncio
import json
import unittest
from types import SimpleNamespace

import httpx
import openai
from livekit.agents import APIConnectOptions, llm
from livekit.agents.voice.agent_session import SessionConnectOptions
from livekit.plugins.openai import LLM

from claim_audit import audit_sentence
from coach import JobCoach
from model_telemetry import UNATTRIBUTED_STAGE, llm_metric_fields, model_stage


def sse_chunk(request_id, content=None, usage=None):
    chunk = {
        "id": request_id,
        "object": "chat.completion.chunk",
        "created": 0,
        "model": "qa-model",
        "choices": [] if usage else [{
            "index": 0, "delta": {"content": content}, "finish_reason": None,
        }],
    }
    if usage:
        chunk["usage"] = usage
    return f"data: {json.dumps(chunk)}\n\n".encode()


class PausedStream(httpx.AsyncByteStream):
    def __init__(self, first, paused):
        self.first = first
        self.paused = paused

    async def __aiter__(self):
        yield self.first
        await self.paused.wait()


class ModelMetricsTests(unittest.IsolatedAsyncioTestCase):
    async def _model(self, respond):
        http = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        client = openai.AsyncClient(
            api_key="qa", base_url="http://qa.invalid/v1", http_client=http
        )
        return LLM(model="qa-model", client=client), client

    async def test_actual_sdk_metrics_keep_concurrent_stage_and_usage(self):
        async def respond(request):
            body = json.loads(request.content)
            response_format = body["response_format"]
            name = (
                "intent" if response_format["type"] == "json_object" else
                "audit" if response_format["json_schema"]["name"] == "AuditResponse" else
                "writer"
            )
            await asyncio.sleep(0.01 if name == "intent" else 0)
            payload = {
                "intent": {"action": "discuss", "filters": {}, "more_options": False},
                "writer": {"sentence": "Okay.", "stance": "neutral"},
                "audit": {"claims": [], "stance": "neutral", "unsupported": []},
            }[name]
            content = sse_chunk(name + "-request", json.dumps(payload))
            usage = sse_chunk(name + "-request", usage={
                "prompt_tokens": 11, "completion_tokens": 4, "total_tokens": 15,
            })
            return httpx.Response(
                200, headers={"Content-Type": "text/event-stream"},
                content=content + usage + b"data: [DONE]\n\n",
            )

        model, client = await self._model(respond)
        observed = []
        model.on("metrics_collected", lambda metrics: observed.append(llm_metric_fields(metrics)))
        session = SimpleNamespace(
            llm=model,
            conn_options=SessionConnectOptions(
                llm_conn_options=APIConnectOptions(timeout=1, max_retry=0)
            ),
        )
        coach = SimpleNamespace(
            state=SimpleNamespace(current_posting=None), session=session
        )

        async def writer():
            async for _ in JobCoach._writer_node(coach, llm.ChatContext.empty(), None):
                pass

        try:
            await asyncio.gather(
                JobCoach._resolve_intent(coach, "Could you explain the tradeoffs?"), writer()
            )
            await audit_sentence(model, "Okay.", {})
        finally:
            await model.aclose()
            await client.close()

        self.assertEqual({item["stage"] for item in observed}, {"intent", "writer", "audit"})
        for item in observed:
            self.assertEqual(item["request_id"], item["stage"] + "-request")
            self.assertEqual(item["prompt_tokens"], 11)
            self.assertEqual(item["completion_tokens"], 4)
            self.assertEqual(item["total_tokens"], 15)
            self.assertGreater(item["tokens_per_second"], 0)

    async def test_actual_sdk_cancelled_scope_resets_and_keeps_stage(self):
        paused = asyncio.Event()

        async def respond(_request):
            return httpx.Response(
                200, headers={"Content-Type": "text/event-stream"},
                stream=PausedStream(sse_chunk("cancel-request", "{"), paused),
            )

        model, client = await self._model(respond)
        observed = []
        model.on("metrics_collected", lambda metrics: observed.append(llm_metric_fields(metrics)))
        received = asyncio.Event()
        restored_stages = []

        async def consume():
            context = llm.ChatContext.empty()
            context.add_message(role="user", content="cancel")
            try:
                with model_stage("writer"):
                    try:
                        with model_stage("audit"):
                            async with model.chat(chat_ctx=context, tools=[]) as stream:
                                await anext(stream)
                                received.set()
                                await asyncio.Event().wait()
                    finally:
                        restored_stages.append(llm_metric_fields(None)["stage"])
            finally:
                restored_stages.append(llm_metric_fields(None)["stage"])

        task = asyncio.create_task(consume())
        try:
            await asyncio.wait_for(received.wait(), 1)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        finally:
            paused.set()
            await model.aclose()
            await client.close()

        self.assertEqual(observed[0]["stage"], "audit")
        self.assertTrue(observed[0]["cancelled"])
        self.assertEqual(restored_stages, ["writer", UNATTRIBUTED_STAGE])
        self.assertEqual(llm_metric_fields(None)["stage"], UNATTRIBUTED_STAGE)


if __name__ == "__main__":
    unittest.main()
