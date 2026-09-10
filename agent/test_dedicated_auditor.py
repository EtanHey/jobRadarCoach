import os
import time
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from audit_model import create_auditor
from coach import JobCoach
from livekit.agents.metrics import LLMMetrics
from main import entrypoint, wire_observability
from model_telemetry import model_stage
from user import User


class TestCoach(JobCoach):
    def __init__(self, session, auditor):
        self.test_session = session
        super().__init__(User.default(), auditor=auditor)

    @property
    def session(self):
        return self.test_session


class EmptyStream:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    def __aiter__(self):
        async def chunks():
            if False:
                yield None
        return chunks()


class Emitter:
    def __init__(self):
        self.handlers = {}

    def on(self, event, callback=None):
        def register(callback):
            self.handlers[event] = callback
            return callback
        return register(callback) if callback is not None else register


class DedicatedAuditorTests(unittest.IsolatedAsyncioTestCase):
    async def test_writer_and_intent_keep_session_model_while_audit_is_dedicated(self):
        writer, auditor = SimpleNamespace(chat=Mock(return_value=EmptyStream())), object()
        session = SimpleNamespace(
            llm=writer,
            userdata=SimpleNamespace(current_posting=None),
            conn_options=SimpleNamespace(llm_conn_options=object()),
        )
        coach = TestCoach(session, auditor)

        with patch.object(JobCoach, "_read_intent_response", AsyncMock(
            return_value='{"action":"discuss","filters":{},"more_options":false}'
        )) as read:
            intent = await coach._resolve_intent("Could you compare the tradeoffs?")
        self.assertEqual(intent.action, "discuss")
        self.assertIs(read.await_args.args[1], writer)

        self.assertEqual(
            [chunk async for chunk in coach._writer_node(Mock(), None)], []
        )
        self.assertEqual(writer.chat.call_count, 1)

        with patch("coach.audit_sentence", AsyncMock()) as audit:
            await coach._audit_speech("Okay.", {})
        self.assertIs(audit.await_args.args[0], auditor)

    async def test_audit_settings_override_writer_defaults_and_close_both_layers(self):
        client = SimpleNamespace(close=AsyncMock())
        model = SimpleNamespace(aclose=AsyncMock())
        env = {
            "LLM_BASE_URL": "http://writer.invalid/v1",
            "LLM_MODEL": "writer-model",
            "AUDIT_LLM_BASE_URL": "http://audit.invalid/v1",
            "AUDIT_LLM_MODEL": "audit-model",
            "LLM_TIMEOUT": "17",
            "LLM_HTTP_RETRIES": "0",
        }
        with patch.dict(os.environ, env, clear=True), \
             patch("audit_model.openai_sdk.AsyncClient", return_value=client) as client_ctor, \
             patch("audit_model.openai_plugin.LLM", return_value=model) as model_ctor:
            runtime = await create_auditor()
            await runtime.aclose()
            await runtime.aclose()

        self.assertEqual(client_ctor.call_args.kwargs["base_url"], env["AUDIT_LLM_BASE_URL"])
        self.assertEqual(client_ctor.call_args.kwargs["max_retries"], 0)
        self.assertEqual(model_ctor.call_args.kwargs.get("temperature"), 0)
        self.assertEqual(client_ctor.call_args.kwargs["timeout"], 17.0)
        self.assertEqual(model_ctor.call_args.kwargs, {"client": client, "model": "audit-model", "temperature": 0})
        model.aclose.assert_awaited_once()
        client.close.assert_awaited_once()

    async def test_default_audit_model_falls_back_to_writer_base_url(self):
        client = SimpleNamespace(close=AsyncMock())
        model = SimpleNamespace(aclose=AsyncMock())
        with patch.dict(os.environ, {"LLM_BASE_URL": "http://writer.invalid/v1"}, clear=True), \
             patch("audit_model.openai_sdk.AsyncClient", return_value=client) as client_ctor, \
             patch("audit_model.openai_plugin.LLM", return_value=model) as model_ctor:
            runtime = await create_auditor()
            await runtime.aclose()
        self.assertEqual(client_ctor.call_args.kwargs["base_url"], "http://writer.invalid/v1")
        self.assertEqual(
            model_ctor.call_args.kwargs["model"], "qwen3:4b-instruct-2507-q4_K_M"
        )

    async def test_model_construction_failure_closes_created_client(self):
        client = SimpleNamespace(close=AsyncMock())
        with patch("audit_model.openai_sdk.AsyncClient", return_value=client), \
             patch("audit_model.openai_plugin.LLM", side_effect=RuntimeError("broken")):
            with self.assertRaisesRegex(RuntimeError, "broken"):
                await create_auditor()
        client.close.assert_awaited_once()

    async def test_entrypoint_startup_failure_closes_dedicated_runtime(self):
        runtime = SimpleNamespace(model=Emitter(), aclose=AsyncMock())
        ctx = SimpleNamespace(add_shutdown_callback=Mock(), room=object())
        whisper = SimpleNamespace(
            set_failure_handler=Mock(),
            capabilities=SimpleNamespace(interim_results=False),
        )
        with patch("main.setup_logging"), \
             patch("main.User.load", AsyncMock(return_value=User.default())), \
             patch("main.list_new_for_me", AsyncMock(return_value=[])), \
             patch("main.speech_components", return_value=(whisper, None)), \
             patch("main.create_auditor", AsyncMock(return_value=runtime)), \
             patch("main.silero.VAD.load", return_value=object()), \
             patch("main.openai.LLM", return_value=object()), \
             patch("main.openai.TTS", return_value=object()), \
             patch("main.AgentSession", side_effect=RuntimeError("startup failed")):
            with self.assertRaisesRegex(RuntimeError, "startup failed"):
                await entrypoint(ctx)
        runtime.aclose.assert_awaited_once()

    def test_dedicated_metrics_keep_audit_stage_request_and_usage(self):
        session, auditor, logger = Emitter(), Emitter(), Mock()
        with patch("main.logging.getLogger", return_value=logger):
            wire_observability(session, SimpleNamespace(), auditor)
            metrics = LLMMetrics(
                label="audit-model", request_id="audit-request", timestamp=time.time(),
                duration=0.2, ttft=0.1, cancelled=False, completion_tokens=7,
                prompt_tokens=13, prompt_cached_tokens=0, total_tokens=20,
                tokens_per_second=35.0,
            )
            with model_stage("audit"):
                auditor.handlers["metrics_collected"](metrics)
        fields = logger.info.call_args.kwargs["extra"]
        self.assertEqual(fields["stage"], "audit")
        self.assertEqual(fields["request_id"], "audit-request")
        self.assertEqual(fields["prompt_tokens"], 13)
        self.assertEqual(fields["completion_tokens"], 7)
        self.assertEqual(fields["tokens_per_second"], 35.0)


if __name__ == "__main__":
    unittest.main()
