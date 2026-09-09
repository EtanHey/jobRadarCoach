import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from livekit.agents.voice.agent_activity import AgentActivity

from main import interruption_options
from stt_whisper import WhisperCppSTT


class BargeInTests(unittest.TestCase):
    def test_actual_sdk_interrupts_sustained_speech_without_waiting_for_final_stt(self):
        with patch.dict(os.environ, {}, clear=True):
            options = interruption_options(WhisperCppSTT())
        speech = SimpleNamespace(interrupted=False, allow_interruptions=True, interrupt=Mock())
        subject = SimpleNamespace(
            _interruption_by_audio_activity_enabled=True,
            _session=SimpleNamespace(
                _aec_warmup_remaining=0, _aec_warmup_timer=None,
                options=SimpleNamespace(interruption=options), agent_state="speaking",
            ),
            _rt_turn_detection_enabled=False, stt=object(),
            _audio_recognition=SimpleNamespace(
                _current_transcript="", _endpointing=SimpleNamespace(overlapping=False),
                _on_start_of_speech=Mock(),
            ),
            _rt_session=None, _current_speech=speech,
            _cancel_false_interruption_timer=Mock(), _pause_enabled=lambda: False,
            _turn_detection="vad", _stt_eos_received=False,
            _user_silence_event=Mock(), min_endpointing_delay=1.2,
        )
        subject._interrupt_by_audio_activity = lambda: AgentActivity._interrupt_by_audio_activity(subject)

        def vad(duration):
            return SimpleNamespace(speech_duration=duration, speaking=True, raw_accumulated_silence=0)

        AgentActivity.on_vad_inference_done(subject, vad(0.2))
        speech.interrupt.assert_not_called()
        AgentActivity.on_vad_inference_done(subject, vad(0.76))
        speech.interrupt.assert_called_once()
        speech.interrupt.reset_mock()
        options["min_words"] = 1
        AgentActivity.on_vad_inference_done(subject, vad(0.76))
        speech.interrupt.assert_not_called()

    def test_explicit_owner_override_and_streaming_word_floor_are_preserved(self):
        with patch.dict(os.environ, {"MIN_INTERRUPTION_WORDS": "2"}, clear=True):
            self.assertEqual(interruption_options(WhisperCppSTT())["min_words"], 2)
        with patch.dict(os.environ, {}, clear=True):
            streaming = SimpleNamespace(capabilities=SimpleNamespace(interim_results=True))
            self.assertEqual(interruption_options(streaming)["min_words"], 1)


if __name__ == "__main__":
    unittest.main()
