import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from livekit.agents import AgentSession, llm
from livekit.agents.voice.agent_activity import AgentActivity
from livekit.agents.voice.audio_recognition import (
    _EndOfTurnInfo,
    _EndOfTurnMetrics,
    _PreemptiveGenerationInfo,
)

from main import turn_handling_options


class CommittedTurnTests(unittest.IsolatedAsyncioTestCase):
    def _activity(self, session):
        return SimpleNamespace(
            _session=session,
            _agent=SimpleNamespace(
                _turn_handling={}, chat_ctx=llm.ChatContext.empty()
            ),
            _scheduling_paused=False,
            _new_turns_blocked=False,
            _current_speech=None,
            llm=Mock(spec=llm.LLM),
            _cancel_preemptive_generation=Mock(),
            _preemptive_generation_count=0,
            _generate_reply=Mock(return_value=Mock()),
            tools=[],
            _tool_choice=None,
            preemptive_generation_opts=session.options.preemptive_generation,
        )

    async def test_final_transcript_waits_for_committed_turn_before_generation(self):
        stt = SimpleNamespace(capabilities=SimpleNamespace(interim_results=False))
        with patch.dict("os.environ", {}, clear=True):
            configured = AgentSession(turn_handling=turn_handling_options(stt))
        default = AgentSession()
        transcript = _PreemptiveGenerationInfo(
            new_transcript="Find me a senior Python role",
            transcript_confidence=1.0,
            started_speaking_at=None,
        )

        default_activity = self._activity(default)
        AgentActivity.on_preemptive_generation(default_activity, transcript)
        default_activity._generate_reply.assert_called_once()

        configured_activity = self._activity(configured)
        AgentActivity.on_preemptive_generation(configured_activity, transcript)
        configured_activity._generate_reply.assert_not_called()

        committed_messages = []

        async def commit_turn(turn_ctx, new_message):
            committed_messages.append(new_message)
            turn_ctx.add_message(role="system", content="COMMITTED_CONTEXT")

        chat_ctx = configured_activity._agent.chat_ctx
        configured_activity._agent._chat_ctx = chat_ctx
        configured_activity._agent.on_user_turn_completed = commit_turn
        configured_activity._rt_turn_detection_enabled = False
        configured_activity._rt_session = None
        configured_activity.stt = None
        configured_activity._turn_detection = "manual"
        configured_activity._interrupt_background_speeches = Mock(return_value=[])
        configured_activity._preemptive_generation = None
        configured_activity._cancel_false_interruption_timer = Mock()
        configured_activity._user_turn_completed_atask = None
        configured_activity._user_turn_completed_task = lambda old_task, turn_info: (
            AgentActivity._user_turn_completed_task(
                configured_activity, old_task, turn_info
            )
        )
        configured_activity._create_speech_task = Mock(return_value="scheduled")
        configured_activity._init_metrics_from_end_of_turn = lambda info: (
            AgentActivity._init_metrics_from_end_of_turn(configured_activity, info)
        )
        speech_handle = SimpleNamespace(id="committed-reply", interrupt=AsyncMock())
        configured_activity._generate_reply = Mock(return_value=speech_handle)
        info = _EndOfTurnInfo(
            skip_reply=False,
            new_transcript=transcript.new_transcript,
            transcript_confidence=transcript.transcript_confidence,
            metrics=_EndOfTurnMetrics(None, None, 0.0, 0.0),
        )

        self.assertTrue(AgentActivity.on_end_of_turn(configured_activity, info))
        configured_activity._create_speech_task.assert_called_once()
        scheduled = configured_activity._create_speech_task.call_args
        self.assertEqual(
            scheduled.kwargs["name"], "AgentActivity._user_turn_completed_task"
        )
        configured_activity._cancel_false_interruption_timer.assert_called_once()
        configured_activity._user_turn_completed_atask = asyncio.current_task()
        await scheduled.args[0]

        configured_activity._generate_reply.assert_called_once()
        generated = configured_activity._generate_reply.call_args.kwargs
        self.assertEqual(generated["user_message"].text_content, transcript.new_transcript)
        self.assertTrue(
            any(
                message.text_content == "COMMITTED_CONTEXT"
                for message in generated["chat_ctx"].messages()
            )
        )
        self.assertEqual(len(committed_messages), 1)
        speech_handle.interrupt.assert_not_awaited()

        self.assertEqual(configured.options.endpointing["min_delay"], 1.2)
        self.assertEqual(configured.options.endpointing["max_delay"], 6.0)
        self.assertEqual(configured.options.interruption["min_duration"], 0.75)


if __name__ == "__main__":
    unittest.main()
