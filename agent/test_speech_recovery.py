import asyncio
import unittest
from types import SimpleNamespace

from speech_recovery import SpeechRecovery
from stt_whisper import normalize_transcript


class SpeechTests(unittest.TestCase):
    def test_parenthesized_real_words_are_not_silence(self):
        for text in ("(I need remote work)", "[Python]", "(blank audio support)"):
            self.assertEqual(normalize_transcript(text), text)
        for text in ("[BLANK_AUDIO]", "[ SILENCE ]", "(blank audio)", "[ INAUDIBLE ]"):
            self.assertEqual(normalize_transcript(text), "")


class RecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_notify_returns_before_speech_and_shutdown_cancels_owned_task(self):
        started = asyncio.Event()
        cancelled = asyncio.Event()

        async def playout():
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        session = SimpleNamespace(say=lambda *_args, **_kwargs: SimpleNamespace(wait_for_playout=playout))
        recovery = SpeechRecovery(session)
        await asyncio.wait_for(recovery.notify(1, 3, RuntimeError("outage")), timeout=0.1)
        await asyncio.wait_for(started.wait(), timeout=0.1)
        await recovery.aclose()
        self.assertTrue(cancelled.is_set())

    async def test_final_failure_speaks_before_shutdown_and_coalesces_pending_errors(self):
        events = []
        released = asyncio.Event()

        async def playout():
            await released.wait()
            events.append("played")

        def say(text, **_kwargs):
            events.append(text)
            return SimpleNamespace(wait_for_playout=playout)

        session = SimpleNamespace(say=say, shutdown=lambda **kw: events.append(("shutdown", kw)))
        recovery = SpeechRecovery(session)
        await recovery.notify(1, 3, RuntimeError("outage"))
        await asyncio.sleep(0)
        await recovery.notify(2, 3, RuntimeError("outage"))
        await recovery.notify(3, 3, RuntimeError("outage"))
        released.set()
        await recovery.task
        self.assertEqual(sum(isinstance(x, str) and "recognition" in x for x in events), 2)
        self.assertEqual(events[-2:], ["played", ("shutdown", {"drain": True})])
        await recovery.aclose()


if __name__ == "__main__":
    unittest.main()
