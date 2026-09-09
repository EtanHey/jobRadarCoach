import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from livekit.agents import AgentSession, llm
from livekit.agents.voice.agent_activity import AgentActivity
from livekit.agents.voice.audio_recognition import _PreemptiveGenerationInfo

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

        async def committed_reply(*_args):
            return None

        configured_activity._rt_turn_detection_enabled = False
        configured_activity.stt = None
        configured_activity._turn_detection = "manual"
        configured_activity._cancel_false_interruption_timer = Mock()
        configured_activity._user_turn_completed_atask = None
        configured_activity._user_turn_completed_task = committed_reply
        configured_activity._create_speech_task = Mock(return_value="scheduled")
        info = SimpleNamespace(skip_reply=False)
        self.assertTrue(AgentActivity.on_end_of_turn(configured_activity, info))
        coroutine = configured_activity._create_speech_task.call_args.args[0]
        coroutine.close()
        self.assertEqual(configured_activity._user_turn_completed_atask, "scheduled")

        self.assertEqual(configured.options.endpointing["min_delay"], 1.2)
        self.assertEqual(configured.options.endpointing["max_delay"], 6.0)
        self.assertEqual(configured.options.interruption["min_duration"], 0.75)


if __name__ == "__main__":
    unittest.main()
