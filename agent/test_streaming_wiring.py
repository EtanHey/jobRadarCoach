import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from livekit.agents import AgentSession

from main import speech_components, turn_handling_options


class StreamingWiringTests(unittest.IsolatedAsyncioTestCase):
    def test_batch_stt_remains_default_without_loading_streaming_factories(self):
        streaming_factory = Mock()
        detector_factory = Mock()
        with patch.dict(os.environ, {}, clear=True):
            stt, detector = speech_components(
                streaming_factory=streaming_factory,
                turn_detector_factory=detector_factory,
            )

        self.assertFalse(stt.capabilities.streaming)
        self.assertIsNone(detector)
        streaming_factory.assert_not_called()
        detector_factory.assert_not_called()

    async def test_streaming_stt_binds_local_detector_into_real_session_options(self):
        stt = SimpleNamespace(capabilities=SimpleNamespace(interim_results=True))
        detector = object()
        streaming_factory = Mock(return_value=stt)
        fake_module = SimpleNamespace(WhisperLiveKitSTT=streaming_factory)
        with (
            patch.dict(os.environ, {"STREAMING_STT_URL": "ws://127.0.0.1:8913/asr?mode=full"}, clear=True),
            patch.dict(sys.modules, {"stt_streaming": fake_module}),
            patch(
                "livekit.plugins.turn_detector.multilingual.MultilingualModel",
                return_value=detector,
            ) as detector_factory,
        ):
            selected, selected_detector = speech_components()
            session = AgentSession(
                vad=None,
                turn_handling=turn_handling_options(selected, turn_detection=selected_detector)
            )

        streaming_factory.assert_called_once_with(
            url="ws://127.0.0.1:8913/asr?mode=full"
        )
        detector_factory.assert_called_once_with()
        self.assertIs(session.options.turn_handling["turn_detection"], detector)
        self.assertFalse(session.options.preemptive_generation["enabled"])
        self.assertEqual(session.options.interruption["min_words"], 1)
        self.assertEqual(session.options.endpointing["min_delay"], 1.2)
        self.assertEqual(session.options.endpointing["max_delay"], 6.0)

    def test_streaming_mode_refuses_remote_eot_override_before_construction(self):
        streaming_factory = Mock()
        detector_factory = Mock()
        with patch.dict(
            os.environ,
            {
                "STREAMING_STT_URL": "ws://127.0.0.1:8913/asr?mode=full",
                "LIVEKIT_REMOTE_EOT_URL": "https://remote.invalid/eot",
            },
            clear=True,
        ):
            with self.assertRaisesRegex(RuntimeError, "LIVEKIT_REMOTE_EOT_URL"):
                speech_components(
                    streaming_factory=streaming_factory,
                    turn_detector_factory=detector_factory,
                )

        streaming_factory.assert_not_called()
        detector_factory.assert_not_called()


if __name__ == "__main__":
    unittest.main()
