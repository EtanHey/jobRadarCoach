import asyncio
import io
import logging
import os
import re
import wave
from collections.abc import Awaitable, Callable

import aiohttp
from livekit import rtc
from livekit.agents import (
    APIConnectionError,
    APIConnectOptions,
    APIStatusError,
    APITimeoutError,
)
from livekit.agents import stt as lkstt
from livekit.agents.language import LanguageCode

_logger = logging.getLogger(__name__)
_WHITESPACE_RE = re.compile(r"\s+")
_BRACKETED_ARTIFACT_RE = re.compile(r"^(?:\[([^\[\]]+)\]|\(([^()]+)\))$")
_SILENCE_MARKERS = {"blank audio", "silence", "inaudible", "no speech", "no audio"}
FailureHandler = Callable[[int, int, BaseException], Awaitable[None]]


def normalize_transcript(text: str) -> str:
    normalized = _WHITESPACE_RE.sub(" ", text).strip()
    if match := _BRACKETED_ARTIFACT_RE.fullmatch(normalized):
        marker = " ".join((match[1] or match[2]).replace("_", " ").casefold().split())
        if marker in _SILENCE_MARKERS:
            return ""
    return normalized


def _bounded_int_env(name: str, default: int, *, minimum: int, maximum: int) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except ValueError:
        value = default
    return min(maximum, max(minimum, value))


def _bounded_float_env(
    name: str, default: float, *, minimum: float, maximum: float
) -> float:
    try:
        value = float(os.environ.get(name, str(default)))
    except ValueError:
        value = default
    return min(maximum, max(minimum, value))


class WhisperCppSTT(lkstt.STT):
    def __init__(
        self,
        url=None,
        language=None,
        *,
        failure_handler: FailureHandler | None = None,
    ):
        super().__init__(capabilities=lkstt.STTCapabilities(streaming=False, interim_results=False))
        self._url = url or os.environ.get("STT_URL", "http://127.0.0.1:8912/inference")
        self._language = LanguageCode(language or os.environ.get("STT_LANGUAGE", "en"))
        self._failure_handler = failure_handler
        self._turn_retries = _bounded_int_env(
            "STT_TURN_RETRIES", 2, minimum=0, maximum=10
        )
        self._retry_backoff = _bounded_float_env(
            "STT_RETRY_BACKOFF_SECONDS", 0.25, minimum=0.0, maximum=30.0
        )
        self._consecutive_failure_limit = _bounded_int_env(
            "STT_CONSECUTIVE_FAILURE_LIMIT", 3, minimum=1, maximum=20
        )
        self._consecutive_failures = 0

    def set_failure_handler(self, handler: FailureHandler) -> None:
        self._failure_handler = handler

    async def _recognize_impl(self, buffer, *, language=None, conn_options=APIConnectOptions()):
        last_error: BaseException | None = None
        for attempt in range(self._turn_retries + 1):
            try:
                event = await self._recognize_once(
                    buffer, language=language, conn_options=conn_options
                )
                if self._consecutive_failures:
                    _logger.info(
                        "speech recognition recovered",
                        extra={
                            "consecutive_failed_turns": self._consecutive_failures,
                        },
                    )
                self._consecutive_failures = 0
                return event
            except (APIConnectionError, APIStatusError, APITimeoutError) as error:
                last_error = error
                if attempt >= self._turn_retries:
                    break
                delay = self._retry_backoff * (2**attempt)
                _logger.warning(
                    "speech recognition attempt failed; retrying",
                    extra={
                        "attempt": attempt + 1,
                        "max_attempts": self._turn_retries + 1,
                        "retry_delay_seconds": delay,
                        "exception_type": type(error).__name__,
                        "exception_message": str(error),
                    },
                )
                await asyncio.sleep(delay)

        assert last_error is not None
        self._consecutive_failures += 1
        _logger.error(
            "speech recognition turn dropped after retries",
            extra={
                "attempts": self._turn_retries + 1,
                "consecutive_failed_turns": self._consecutive_failures,
                "consecutive_failure_limit": self._consecutive_failure_limit,
                "exception_type": type(last_error).__name__,
                "exception_message": str(last_error),
            },
            exc_info=(type(last_error), last_error, last_error.__traceback__),
        )
        if self._failure_handler is not None:
            await self._failure_handler(
                self._consecutive_failures,
                self._consecutive_failure_limit,
                last_error,
            )
        requested_language = language if isinstance(language, str) else self._language
        return lkstt.SpeechEvent(
            type=lkstt.SpeechEventType.FINAL_TRANSCRIPT,
            alternatives=[lkstt.SpeechData(text="", language=requested_language)],
        )

    async def _recognize_once(
        self, buffer, *, language=None, conn_options=APIConnectOptions()
    ):
        frame = rtc.combine_audio_frames(buffer)
        wav = io.BytesIO()
        with wave.open(wav, "wb") as w:
            w.setnchannels(frame.num_channels)
            w.setsampwidth(2)
            w.setframerate(frame.sample_rate)
            w.writeframes(frame.data)
        form = aiohttp.FormData()
        form.add_field("file", wav.getvalue(), filename="a.wav", content_type="audio/wav")
        form.add_field("response_format", "json")
        requested_language = language if isinstance(language, str) else self._language
        form.add_field("language", str(requested_language))
        timeout = aiohttp.ClientTimeout(total=conn_options.timeout)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(self._url, data=form) as response:
                    if response.status >= 400:
                        body = (await response.text())[:500]
                        raise APIStatusError(
                            "whisper server returned an error",
                            status_code=response.status,
                            body=body,
                        )
                    payload = await response.json()
        except asyncio.TimeoutError as error:
            raise APITimeoutError("whisper server timed out") from error
        except aiohttp.ClientError as error:
            raise APIConnectionError("whisper server connection failed") from error
        text = payload.get("text")
        if not isinstance(text, str):
            raise APIStatusError("whisper server response did not contain text")
        text = normalize_transcript(text)
        return lkstt.SpeechEvent(
            type=lkstt.SpeechEventType.FINAL_TRANSCRIPT,
            alternatives=[
                lkstt.SpeechData(text=text, language=requested_language)
            ],
        )
