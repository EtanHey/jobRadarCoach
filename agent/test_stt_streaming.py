import asyncio
import json
import time
import unittest
from unittest.mock import patch

from livekit import rtc
from livekit.agents import APIConnectionError, APIConnectOptions, APIStatusError, APITimeoutError
from livekit.agents import stt as lkstt
from livekit.agents.voice import AgentSession
from livekit.agents.voice.audio_recognition import _STTPipeline

from stt_streaming import WhisperLiveKitSTT


class FakeSocket:
    def __init__(self, updates=(), *, acknowledge_eof=True, server_config=None):
        self.sent = []
        self.closed = False
        self._updates = updates
        self._acknowledge_eof = acknowledge_eof
        self._incoming = asyncio.Queue()
        config = server_config if server_config is not None else {
            "type": "config", "useAudioWorklet": True, "mode": "full"
        }
        self._incoming.put_nowait(json.dumps(config))

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        self.closed = True

    async def send(self, data):
        self.sent.append(data)
        if isinstance(data, bytes) and data and not self._incoming.qsize():
            for update in self._updates:
                await self._incoming.put(json.dumps(update))
        if data == b"" and self._acknowledge_eof:
            await self._incoming.put(json.dumps({"type": "ready_to_stop"}))
            await self._incoming.put(None)

    def __aiter__(self):
        return self

    async def __anext__(self):
        item = await self._incoming.get()
        if item is None:
            raise StopAsyncIteration
        return item

    async def recv(self):
        return await self.__anext__()


class Connector:
    def __init__(self, *sockets):
        self.sockets = sockets
        self.calls = []

    def __call__(self, url, **kwargs):
        socket = self.sockets[min(len(self.calls), len(self.sockets) - 1)]
        self.calls.append((url, kwargs))
        return socket


class FailingSocket(FakeSocket):
    async def send(self, data):
        self.sent.append(data)
        if isinstance(data, bytes):
            await self._incoming.put(json.dumps({"error": "backend unavailable"}))


def frame(data=b"\x01\x00\x02\x00"):
    return rtc.AudioFrame(data=data, sample_rate=16000, num_channels=1,
                          samples_per_channel=len(data) // 2)


async def collect(stt, audio=None):
    stream = stt.stream(conn_options=APIConnectOptions(timeout=4, max_retry=0))
    stream.push_frame(audio or frame())
    stream.end_input()
    try:
        return await drain(stream)
    finally:
        await stream.aclose()


async def drain(stream):
    return [event async for event in stream]


class StreamingProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def test_early_ready_ack_cancels_sender_with_input_open(self):
        socket = FakeSocket([])
        socket._incoming.put_nowait(json.dumps({"type": "ready_to_stop"}))
        stt = WhisperLiveKitSTT(connect=Connector(socket))
        stream = stt.stream(conn_options=APIConnectOptions(timeout=0.1, max_retry=0))
        self.assertEqual(await asyncio.wait_for(drain(stream), 0.5), [])
        await stream.aclose()
        self.assertTrue(socket.closed)
        self.assertTrue(stream._sender_task.done())
        self.assertTrue(stream._receiver_task.done())

    async def test_eof_acknowledgement_is_bounded_by_connection_timeout(self):
        failures = []

        async def failed(_count, _limit, error):
            failures.append(error)

        socket = FakeSocket([], acknowledge_eof=False)
        stt = WhisperLiveKitSTT(connect=Connector(socket), failure_handler=failed)
        stream = stt.stream(conn_options=APIConnectOptions(timeout=0.01, max_retry=0))
        stream.end_input()
        with self.assertRaises(APITimeoutError):
            await asyncio.wait_for(drain(stream), 0.5)
        await stream.aclose()
        self.assertIsInstance(failures[0], APITimeoutError)
        self.assertTrue(socket.closed)

    async def test_incompatible_server_config_sends_no_audio(self):
        socket = FakeSocket(
            [], server_config={"type": "config", "useAudioWorklet": False, "mode": "full"}
        )
        stt = WhisperLiveKitSTT(connect=Connector(socket))
        with self.assertRaisesRegex(APIStatusError, "incompatible"):
            await collect(stt)
        self.assertEqual(socket.sent, [])
        self.assertTrue(socket.closed)

    async def test_pcm_handshake_interim_final_eof_and_cleanup(self):
        socket = FakeSocket(
            [
                {
                    "status": "active_transcription",
                    "lines": [],
                    "buffer_transcription": "Hel",
                },
                {
                    "status": "active_transcription",
                    "lines": [
                        {
                            "speaker": 1,
                            "text": "Hello",
                            "start": "0:00:00",
                            "end": "0:00:01.5",
                        }
                    ],
                    "buffer_transcription": "world",
                },
            ]
        )
        connector = Connector(socket)
        events = await collect(WhisperLiveKitSTT(connect=connector))
        self.assertEqual(socket.sent, [b"\x01\x00\x02\x00", b""])
        self.assertEqual(connector.calls[0][0], "ws://127.0.0.1:8913/asr?mode=full")
        self.assertEqual(connector.calls[0][1]["open_timeout"], 4)
        self.assertEqual([event.type for event in events], [
            lkstt.SpeechEventType.INTERIM_TRANSCRIPT,
            lkstt.SpeechEventType.FINAL_TRANSCRIPT,
            lkstt.SpeechEventType.INTERIM_TRANSCRIPT,
        ])
        self.assertEqual([event.alternatives[0].text for event in events], ["Hel", "Hello", "world"])
        self.assertEqual(events[1].alternatives[0].end_time, 1.5)
        self.assertTrue(socket.closed)

    def test_diarization_is_rejected_by_runtime_contract(self):
        stt = WhisperLiveKitSTT()
        self.assertTrue(stt.capabilities.streaming)
        self.assertTrue(stt.capabilities.interim_results)
        with self.assertRaisesRegex(ValueError, "diarization=False"):
            WhisperLiveKitSTT(diarization=True)

    async def test_server_error_and_invalid_audio_are_observable(self):
        for updates, audio, expected in (
            ([{"error": "backend unavailable"}], frame(), "backend unavailable"),
            (["invalid update"], frame(), "update must be an object"),
            ([], rtc.AudioFrame(data=b"\0" * 8, sample_rate=16000, num_channels=2, samples_per_channel=2), "mono PCM"),
        ):
            with self.subTest(expected=expected):
                failures = []

                async def failed(_count, _limit, error):
                    failures.append(str(error))

                socket = FakeSocket(updates)
                stt = WhisperLiveKitSTT(connect=Connector(socket), failure_handler=failed)
                with self.assertRaises(APIStatusError):
                    await collect(stt, audio)
                self.assertIn(expected, failures[0])
                self.assertTrue(socket.closed)

    async def test_failed_stream_disables_same_channel_retry_and_replay(self):
        failures = []

        async def failed(count, limit, error):
            failures.append((count, limit, str(error)))

        sockets = [FailingSocket(), FailingSocket()]
        connector = Connector(*sockets)
        stt = WhisperLiveKitSTT(connect=connector, failure_handler=failed)
        stream = stt.stream(
            conn_options=APIConnectOptions(timeout=1, max_retry=1, retry_interval=0)
        )
        stream.push_frame(frame())
        stream.end_input()
        with self.assertRaises(APIStatusError):
            _ = [event async for event in stream]
        await stream.aclose()
        self.assertEqual(len(connector.calls), 1)
        self.assertEqual(sockets[0].sent, [b"\x01\x00\x02\x00", b""])
        self.assertEqual(sockets[1].sent, [])
        self.assertTrue(sockets[0].closed)
        self.assertEqual([failure[:2] for failure in failures], [(1, 3)])
        self.assertEqual(stream._conn_options.timeout, 1)
        self.assertEqual(stream._conn_options.retry_interval, 0)
        self.assertEqual(stream._conn_options.max_retry, 0)

    async def test_sdk_pipeline_recreates_stream_for_fresh_audio(self):
        received = []
        stream_calls = 0
        stream_recreated = asyncio.Event()

        async def stt_node(audio, _settings):
            nonlocal stream_calls
            call = stream_calls
            stream_calls += 1
            if call == 1:
                stream_recreated.set()
            async for audio_frame in audio:
                received.append((call, bytes(audio_frame.data)))
                if call == 0:
                    raise APIConnectionError("first stream failed")
                yield lkstt.SpeechEvent(type=lkstt.SpeechEventType.FINAL_TRANSCRIPT)

        with patch(
            "livekit.agents.voice.audio_recognition._STT_RECONNECT_INTERVAL", 0
        ):
            pipeline = _STTPipeline(stt_node)
            try:
                pipeline.audio_ch.send_nowait(frame(b"\x01\x00\x02\x00"))
                await asyncio.wait_for(stream_recreated.wait(), 0.5)
                self.assertEqual(stream_calls, 2)
                pipeline.audio_ch.send_nowait(frame(b"\x03\x00\x04\x00"))
                event = await asyncio.wait_for(anext(pipeline.event_ch), 0.5)
                self.assertEqual(event.type, lkstt.SpeechEventType.FINAL_TRANSCRIPT)
                self.assertEqual(received, [
                    (0, b"\x01\x00\x02\x00"),
                    (1, b"\x03\x00\x04\x00"),
                ])
            finally:
                await pipeline.aclose()

    async def test_first_unrecoverable_stt_error_is_tolerated_by_session(self):
        session = AgentSession()
        session._on_error(lkstt.STTError(
            timestamp=time.time(),
            label="streaming-stt",
            error=APIConnectionError("stream failed"),
            recoverable=False,
        ))
        self.assertEqual(session._stt_error_counts, 1)
        self.assertIsNone(session._closing_task)

    async def test_aclose_cancels_open_input_sender_and_receiver(self):
        socket = FakeSocket([])
        stt = WhisperLiveKitSTT(connect=Connector(socket))
        stream = stt.stream(conn_options=APIConnectOptions(timeout=1, max_retry=0))
        stream.push_frame(frame())
        for _ in range(20):
            if len(socket.sent) >= 2:
                break
            await asyncio.sleep(0)
        await asyncio.wait_for(stream.aclose(), timeout=0.5)
        self.assertTrue(socket.closed)
        self.assertTrue(stream._sender_task.done())
        self.assertTrue(stream._receiver_task.done())


if __name__ == "__main__":
    unittest.main()
