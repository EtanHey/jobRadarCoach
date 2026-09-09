import asyncio
import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from livekit.agents import APIConnectionError
from livekit.agents import stt as lkstt
from livekit.agents.voice.audio_recognition import AudioRecognition

from coach import extract_job_filter_updates
from main import register_ping_rpc
from stt_whisper import WhisperCppSTT, normalize_transcript
from tools import JobFilters, Posting, SessionState


class TranscriptTests(unittest.TestCase):
    def test_whisper_artifacts_are_empty_and_whitespace_is_flattened(self):
        for artifact in (
            "[BLANK_AUDIO]",
            " [ silence ] ",
            "[ INAUDIBLE ]",
            "(blank_audio)",
            "( BLANK AUDIO )",
        ):
            with self.subTest(artifact=artifact):
                self.assertEqual(normalize_transcript(artifact), "")
        self.assertEqual(
            normalize_transcript("Can you\n find\tme something in Israel?"),
            "Can you find me something in Israel?",
        )

    def test_empty_final_transcript_never_reaches_user_turn_hook(self):
        calls = []
        recognition = object.__new__(AudioRecognition)
        recognition._stt_pipeline = None
        recognition._vad = None
        recognition._last_speaking_time = None
        recognition._turn_detection_mode = "vad"
        recognition._last_language = None
        recognition._final_transcript_received = asyncio.Event()
        recognition._hooks = SimpleNamespace(
            on_final_transcript=lambda *_args, **_kwargs: calls.append("user turn")
        )
        event = lkstt.SpeechEvent(
            type=lkstt.SpeechEventType.FINAL_TRANSCRIPT,
            alternatives=[lkstt.SpeechData(text="", language="en")],
        )

        recognition._process_stt_event(event)

        self.assertEqual(calls, [])


class FilterTests(unittest.TestCase):
    def test_spoken_filter_shapes_are_extracted_without_inference(self):
        updates, clear = extract_job_filter_updates(
            "Find me a senior remote Python role in Israel with a score above 70."
        )
        self.assertFalse(clear)
        self.assertEqual(
            updates,
            {
                "location": "Israel",
                "remote": True,
                "seniority": "senior",
                "min_score": 70,
                "query": "Python",
            },
        )
        self.assertEqual(extract_job_filter_updates("I have at least 4 years."), ({}, False))

    def test_candidate_replacement_resets_serialized_cursor(self):
        first = Posting(
            id=uuid4(),
            title="First",
            company="One",
            location="Arizona",
            score=90,
            reasons="",
            apply_url="https://example.com/first",
        )
        replacement = Posting(
            id=uuid4(),
            title="Replacement",
            company="Two",
            location="Israel",
            score=80,
            reasons="",
            apply_url="https://example.com/replacement",
        )
        state = SessionState(candidates=(first,))
        self.assertIs(state.advance(), first)
        filters = JobFilters(location="Israel")
        state.replace_candidates([replacement], filters=filters)
        self.assertEqual(state.cursor, -1)
        self.assertIsNone(state.current_posting)
        self.assertIs(state.advance(), replacement)


class PingTests(unittest.TestCase):
    def test_ping_registers_static_read_only_response(self):
        registered = {}

        class LocalParticipant:
            def register_rpc_method(self, method, handler):
                registered[method] = handler

        ctx = SimpleNamespace(
            room=SimpleNamespace(local_participant=LocalParticipant())
        )
        register_ping_rpc(ctx)
        self.assertEqual(registered["jrc.ping"](SimpleNamespace(payload="ignored")), "pong")


class STTFailureTests(unittest.IsolatedAsyncioTestCase):
    async def test_failure_retries_drop_turn_and_reset_after_success(self):
        announcements = []

        async def announce(count, limit, _error):
            announcements.append((count, limit))

        with patch.dict(
            os.environ,
            {
                "STT_TURN_RETRIES": "2",
                "STT_RETRY_BACKOFF_SECONDS": "0.1",
                "STT_CONSECUTIVE_FAILURE_LIMIT": "2",
            },
        ):
            subject = WhisperCppSTT(failure_handler=announce)

        attempts = 0

        async def always_fail(*_args, **_kwargs):
            nonlocal attempts
            attempts += 1
            raise APIConnectionError("synthetic outage")

        subject._recognize_once = always_fail
        sleep = AsyncMock()
        with patch("stt_whisper.asyncio.sleep", sleep):
            first = await subject._recognize_impl([])
            second = await subject._recognize_impl([])

        self.assertEqual(first.alternatives[0].text, "")
        self.assertEqual(second.alternatives[0].text, "")
        self.assertEqual(announcements, [(1, 2), (2, 2)])
        self.assertEqual(attempts, 6)
        self.assertEqual(
            [call.args[0] for call in sleep.await_args_list],
            [0.1, 0.2, 0.1, 0.2],
        )

        async def recover(*_args, **_kwargs):
            return lkstt.SpeechEvent(
                type=lkstt.SpeechEventType.FINAL_TRANSCRIPT,
                alternatives=[lkstt.SpeechData(text="recovered", language="en")],
            )

        subject._recognize_once = recover
        recovered = await subject._recognize_impl([])
        self.assertEqual(recovered.alternatives[0].text, "recovered")
        self.assertEqual(subject._consecutive_failures, 0)


if __name__ == "__main__":
    unittest.main()
