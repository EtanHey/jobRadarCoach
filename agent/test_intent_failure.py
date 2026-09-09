"""Failed interpretation must not launch another speculative model request."""
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from livekit.agents import llm

from coach import JobCoach
from intent import Intent
from test_speech_stream import CoachUnderTest
from tools import SessionState


class IntentFailureTests(unittest.IsolatedAsyncioTestCase):
    async def test_failed_intent_skips_writer_and_captures_only_clarification(self):
        state = SessionState()
        coach = CoachUnderTest(state)
        context = llm.ChatContext.empty()
        context.add_message(role="user", content="some jobs in Israel")
        writer = Mock(side_effect=AssertionError("writer must not run after intent failure"))
        with patch.object(coach, "_resolve_intent", AsyncMock(return_value=None)), \
                patch.object(coach, "_writer_node", writer), self.assertLogs("coach", "INFO") as logs:
            output = [part async for part in coach.llm_node(context, [], None)]
        writer.assert_not_called()
        self.assertEqual(output, [state.deterministic_reply])
        self.assertEqual(state.intended_text, output[0])
        self.assertEqual(state.cursor, -1)
        self.assertIsNone(state.turn_posting)
        captured = next(r for r in logs.records if r.msg == "assistant intended text captured")
        self.assertEqual(captured.model_text, "")
        self.assertIsNone(captured.grounded_posting_id)

    async def test_next_resolved_turn_still_uses_natural_writer_without_posting(self):
        state = SessionState()
        coach = CoachUnderTest(state)
        context = llm.ChatContext.empty()
        message = context.add_message(role="user", content="unclear")
        with patch.object(coach, "_resolve_intent", AsyncMock(return_value=None)):
            await coach._prepare_turn(context, message)
        context.add_message(role="user", content="pause")
        calls = []

        async def writer(*_args):
            calls.append(True)
            yield json.dumps({"sentence": "Sure, take your time.", "stance": "neutral"})

        with patch.object(coach, "_resolve_intent", AsyncMock(return_value=Intent("pause"))), \
                patch.object(coach, "_writer_node", writer):
            output = [part async for part in coach.llm_node(context, [], None)]
        self.assertEqual(calls, [True])
        self.assertEqual(output, ["Sure, take your time. "])

    async def test_empty_timeout_message_has_a_stable_failure_reason(self):
        model = SimpleNamespace(chat=Mock(side_effect=TimeoutError()))
        coach = SimpleNamespace(state=SessionState(), session=SimpleNamespace(llm=model))
        with self.assertLogs("coach", "WARNING") as logs:
            intent = await JobCoach._resolve_intent(coach, "some jobs in Israel")
        self.assertIsNone(intent)
        self.assertEqual(logs.records[0].reason, "intent_timeout")


if __name__ == "__main__":
    unittest.main()
