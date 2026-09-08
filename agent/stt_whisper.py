import asyncio
import io
import os
import wave

import aiohttp
from livekit import rtc
from livekit.agents import (
    APIConnectOptions,
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
)
from livekit.agents import stt as lkstt
from livekit.agents.language import LanguageCode


class WhisperCppSTT(lkstt.STT):
    def __init__(self, url=None, language=None):
        super().__init__(capabilities=lkstt.STTCapabilities(streaming=False, interim_results=False))
        self._url = url or os.environ.get("STT_URL", "http://127.0.0.1:8910/inference")
        self._language = LanguageCode(language or os.environ.get("STT_LANGUAGE", "en"))

    async def _recognize_impl(self, buffer, *, language=None, conn_options=APIConnectOptions()):
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
        return lkstt.SpeechEvent(
            type=lkstt.SpeechEventType.FINAL_TRANSCRIPT,
            alternatives=[
                lkstt.SpeechData(text=text.strip(), language=requested_language)
            ],
        )
