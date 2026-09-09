from livekit.agents import APIStatusError
from livekit.agents import stt as lkstt
from livekit.agents.language import LanguageCode


def _seconds(timestamp: str) -> float:
    try:
        hours, minutes, seconds = timestamp.split(":")
        return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    except (AttributeError, TypeError, ValueError) as error:
        raise APIStatusError("invalid WhisperLiveKit line timestamp") from error


def _line_identity(line: object) -> tuple[int, str | None, str, str]:
    if not isinstance(line, dict):
        raise APIStatusError("WhisperLiveKit line must be an object")
    speaker = line.get("speaker")
    text = line.get("text")
    start = line.get("start")
    end = line.get("end")
    if (
        not isinstance(speaker, int)
        or isinstance(speaker, bool)
        or not (isinstance(text, str) or text is None)
        or not isinstance(start, str)
        or not isinstance(end, str)
    ):
        raise APIStatusError("invalid WhisperLiveKit line schema")
    _seconds(start)
    _seconds(end)
    return speaker, text, start, end


class FullHistory:
    def __init__(self, language: LanguageCode) -> None:
        self._language = language
        self._committed: list[tuple[int, str | None, str, str]] = []

    def consume(self, payload: object) -> list[lkstt.SpeechEvent]:
        if not isinstance(payload, dict):
            raise APIStatusError("WhisperLiveKit update must be an object")
        error = payload.get("error")
        if error is not None:
            if not isinstance(error, str):
                raise APIStatusError("WhisperLiveKit error must be a string")
            raise APIStatusError(f"WhisperLiveKit error: {error}")
        if payload.get("type") == "ready_to_stop":
            return []
        if payload.get("status") not in {"active_transcription", "no_audio_detected"}:
            raise APIStatusError("unsupported WhisperLiveKit update")
        lines = payload.get("lines")
        interim = payload.get("buffer_transcription")
        if not isinstance(lines, list) or not isinstance(interim, str):
            raise APIStatusError("invalid WhisperLiveKit update schema")
        snapshot = [_line_identity(line) for line in lines]
        if len(snapshot) < len(self._committed):
            raise APIStatusError("WhisperLiveKit truncated committed transcript history")
        events = []
        for index, line in enumerate(snapshot):
            previous = self._committed[index] if index < len(self._committed) else None
            event = self._committed_suffix(previous, line)
            if event is not None:
                events.append(event)
        self._committed = snapshot
        if interim:
            events.append(self._event(lkstt.SpeechEventType.INTERIM_TRANSCRIPT, interim))
        return events

    def _committed_suffix(
        self,
        previous: tuple[int, str | None, str, str] | None,
        current: tuple[int, str | None, str, str],
    ) -> lkstt.SpeechEvent | None:
        speaker, text, start, end = current
        if speaker == -2:
            if text not in {None, ""}:
                raise APIStatusError("WhisperLiveKit silence line contains text")
            if previous is not None:
                if previous[:3] != current[:3] or _seconds(end) < _seconds(previous[3]):
                    raise APIStatusError("WhisperLiveKit rewrote committed silence")
            return None
        if not isinstance(text, str):
            raise APIStatusError("WhisperLiveKit speech line has no text")
        prior_text = ""
        suffix_start = _seconds(start)
        if previous is not None:
            prior_speaker, old_text, old_start, old_end = previous
            if (
                prior_speaker != speaker
                or old_start != start
                or not isinstance(old_text, str)
                or not text.startswith(old_text)
                or _seconds(end) < _seconds(old_end)
            ):
                raise APIStatusError("WhisperLiveKit rewrote committed transcript history")
            prior_text = old_text
            suffix_start = _seconds(old_end)
        suffix = text[len(prior_text) :].lstrip()
        if not suffix:
            return None
        return self._event(
            lkstt.SpeechEventType.FINAL_TRANSCRIPT,
            suffix,
            start=suffix_start,
            end=_seconds(end),
            speaker=str(speaker),
        )

    def _event(
        self,
        event_type: lkstt.SpeechEventType,
        text: str,
        *,
        start: float = 0.0,
        end: float = 0.0,
        speaker: str | None = None,
    ) -> lkstt.SpeechEvent:
        return lkstt.SpeechEvent(
            type=event_type,
            alternatives=[
                lkstt.SpeechData(
                    language=self._language, text=text, start_time=start,
                    end_time=end, speaker_id=speaker,
                )
            ],
        )
