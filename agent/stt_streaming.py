import asyncio
import json
import logging
import os
from collections.abc import Awaitable, Callable
from dataclasses import replace
from typing import Any

import websockets
from livekit.agents import (
    APIConnectionError,
    APIConnectOptions,
    APIStatusError,
    APITimeoutError,
)
from livekit.agents import stt as lkstt
from livekit.agents.language import LanguageCode
from stt_streaming_history import FullHistory

_logger = logging.getLogger(__name__)
FailureHandler = Callable[[int, int, BaseException], Awaitable[None]]
Connect = Callable[..., Any]


class WhisperLiveKitSTT(lkstt.STT):
    def __init__(
        self,
        url: str | None = None,
        language: str | None = None,
        *,
        failure_handler: FailureHandler | None = None,
        connect: Connect = websockets.connect,
        diarization: bool = False,
    ) -> None:
        if diarization:
            raise ValueError("WhisperLiveKitSTT requires diarization=False")
        super().__init__(capabilities=lkstt.STTCapabilities(streaming=True, interim_results=True))
        self._url = url or os.environ.get("STREAMING_STT_URL", "ws://127.0.0.1:8913/asr?mode=full")
        self._language = LanguageCode(language or os.environ.get("STT_LANGUAGE", "en"))
        self._failure_handler = failure_handler
        self._connect = connect
        self._consecutive_failures = 0
        try:
            failure_limit = int(os.environ.get("STT_CONSECUTIVE_FAILURE_LIMIT", "3"))
        except ValueError:
            failure_limit = 3
        self._failure_limit = min(20, max(1, failure_limit))

    def set_failure_handler(self, handler: FailureHandler) -> None:
        self._failure_handler = handler

    async def _recognize_impl(self, buffer, *, language, conn_options):
        raise NotImplementedError("WhisperLiveKitSTT supports streaming recognition only")

    def stream(self, *, language=None, conn_options=APIConnectOptions()):
        requested = language if isinstance(language, str) else str(self._language)
        # RecognizeStream retries reuse a one-shot audio channel. Once PCM has been
        # consumed, reconnecting here would open an empty stream; the SDK pipeline
        # instead recreates this stream around its durable live-audio channel.
        conn_options = replace(conn_options, max_retry=0)
        return _WhisperLiveKitStream(stt=self, language=LanguageCode(requested), conn_options=conn_options)

    async def _notify_failure(self, error: BaseException) -> None:
        self._consecutive_failures += 1
        _logger.error(
            "streaming speech recognition stream failed",
            extra={"consecutive_failures": self._consecutive_failures},
            exc_info=(type(error), error, error.__traceback__),
        )
        if self._failure_handler is not None:
            try:
                await self._failure_handler(
                    self._consecutive_failures, self._failure_limit, error
                )
            except Exception:
                _logger.exception("streaming STT failure handler failed")


class _WhisperLiveKitStream(lkstt.RecognizeStream):
    def __init__(self, *, stt: WhisperLiveKitSTT, language, conn_options) -> None:
        super().__init__(stt=stt, conn_options=conn_options, sample_rate=16000)
        self._provider = stt
        self._language = language
        self._sender_task: asyncio.Task | None = None
        self._receiver_task: asyncio.Task | None = None

    async def _run(self) -> None:
        history = FullHistory(self._language)
        try:
            async with self._provider._connect(
                self._provider._url, open_timeout=self._conn_options.timeout
            ) as socket:
                try:
                    raw_config = await asyncio.wait_for(
                        socket.recv(), timeout=self._conn_options.timeout
                    )
                except TimeoutError as error:
                    raise APITimeoutError(
                        "WhisperLiveKit config handshake timed out"
                    ) from error
                try:
                    config = json.loads(raw_config) if isinstance(raw_config, str) else None
                except json.JSONDecodeError as error:
                    raise APIStatusError("malformed WhisperLiveKit config") from error
                if not (
                    isinstance(config, dict)
                    and config.get("type") == "config"
                    and config.get("useAudioWorklet") is True
                    and config.get("mode") == "full"
                ):
                    raise APIStatusError("incompatible WhisperLiveKit config")
                sender = self._sender_task = asyncio.create_task(self._send_audio(socket))
                receiver = self._receiver_task = asyncio.create_task(
                    self._receive(socket, history)
                )
                try:
                    done, _pending = await asyncio.wait(
                        {sender, receiver}, return_when=asyncio.FIRST_COMPLETED
                    )
                    if receiver in done:
                        await receiver
                        if sender.done():
                            await sender
                    else:
                        await sender
                        try:
                            await asyncio.wait_for(
                                receiver, timeout=self._conn_options.timeout
                            )
                        except TimeoutError as error:
                            raise APITimeoutError(
                                "WhisperLiveKit EOF acknowledgement timed out"
                            ) from error
                finally:
                    for task in (sender, receiver):
                        if not task.done():
                            task.cancel()
                    await asyncio.gather(sender, receiver, return_exceptions=True)
            self._provider._consecutive_failures = 0
        except asyncio.CancelledError:
            raise
        except Exception as error:
            wrapped = (
                error
                if isinstance(error, (APIConnectionError, APIStatusError))
                else APIConnectionError(f"WhisperLiveKit WebSocket failed: {error}")
            )
            await self._provider._notify_failure(wrapped)
            if wrapped is error:
                raise
            raise wrapped from error

    async def _receive(self, socket, history: FullHistory) -> None:
        async for raw in socket:
            if not isinstance(raw, str):
                raise APIStatusError("WhisperLiveKit update must be text JSON")
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError as error:
                raise APIStatusError("malformed WhisperLiveKit JSON") from error
            for event in history.consume(payload):
                self._event_ch.send_nowait(event)
            if isinstance(payload, dict) and payload.get("type") == "ready_to_stop":
                return
        raise APIConnectionError("WhisperLiveKit closed before ready_to_stop")

    async def _send_audio(self, socket) -> None:
        async for item in self._input_ch:
            if isinstance(item, self._FlushSentinel):
                continue
            if item.sample_rate != 16000 or item.num_channels != 1:
                raise APIStatusError("WhisperLiveKit requires 16 kHz mono PCM")
            pcm = bytes(item.data)
            if len(pcm) != item.samples_per_channel * 2:
                raise APIStatusError("WhisperLiveKit requires s16le PCM")
            await socket.send(pcm)
        await socket.send(b"")
