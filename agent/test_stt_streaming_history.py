import unittest

from livekit.agents import APIStatusError
from livekit.agents import stt as lkstt
from livekit.agents.language import LanguageCode

from stt_streaming_history import FullHistory


def line(text, start, end, *, speaker=0):
    return {"speaker": speaker, "text": text, "start": start, "end": end}


def update(lines, buffer=""):
    return {
        "status": "active_transcription",
        "lines": lines,
        "buffer_transcription": buffer,
    }


class FullHistoryTests(unittest.TestCase):
    def setUp(self):
        self.history = FullHistory(LanguageCode("en"))

    def consume_all(self, *updates):
        return [event for payload in updates for event in self.history.consume(payload)]

    def test_open_line_growth_emits_only_new_committed_suffix(self):
        first = line("hello", "0:00:00", "0:00:01")
        grown = line("hello world", "0:00:00", "0:00:02")
        events = self.consume_all(
            update([first], "wor"), update([grown]), update([grown])
        )
        finals = [e for e in events if e.type == lkstt.SpeechEventType.FINAL_TRANSCRIPT]

        self.assertEqual([e.alternatives[0].text for e in finals], ["hello", "world"])
        self.assertEqual(
            [(e.alternatives[0].start_time, e.alternatives[0].end_time) for e in finals],
            [(0.0, 1.0), (1.0, 2.0)],
        )
        self.assertEqual(events[1].type, lkstt.SpeechEventType.INTERIM_TRANSCRIPT)

    def test_silence_growth_and_sealed_repeats_emit_nothing_twice(self):
        first = line("one", "0:00:00", "0:00:01", speaker=1)
        silence = line(None, "0:00:01", "0:00:02", speaker=-2)
        extended = {**silence, "end": "0:00:02.5"}
        second = line("two", "0:00:03", "0:00:04", speaker=2)
        events = self.consume_all(
            update([first]),
            update([first, silence]),
            update([first, extended]),
            update([first, extended]),
            update([first, extended, second]),
        )

        self.assertEqual([e.alternatives[0].text for e in events], ["one", "two"])
        self.assertEqual([e.alternatives[0].speaker_id for e in events], ["1", "2"])

    def test_committed_rewrite_and_truncation_are_rejected(self):
        first = line("one", "0:00:00", "0:00:01", speaker=1)
        self.history.consume(update([first]))
        with self.assertRaisesRegex(APIStatusError, "rewrote committed transcript"):
            self.history.consume(update([{**first, "text": "changed"}]))

        history = FullHistory(LanguageCode("en"))
        history.consume(update([first, line(None, "0:00:01", "0:00:02", speaker=-2)]))
        with self.assertRaisesRegex(APIStatusError, "truncated committed transcript"):
            history.consume(update([first]))


if __name__ == "__main__":
    unittest.main()
