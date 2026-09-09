"""Announce STT failures without holding up recognition or leaving orphan tasks."""

import asyncio
import logging


class SpeechRecovery:
    def __init__(self, session):
        self.session = session
        self.task: asyncio.Task | None = None
        self.pending: tuple[int, int] | None = None
        self.closed = False

    async def notify(self, count: int, limit: int, error: BaseException) -> None:
        if self.closed:
            return
        logging.getLogger(__name__).warning(
            "speech recognition failure queued",
            extra={"consecutive_failed_turns": count, "consecutive_failure_limit": limit,
                   "exception_type": type(error).__name__, "disconnecting": count >= limit},
        )
        # Keep only the latest pending failure, not an unbounded queue of speech.
        self.pending = (count, limit)
        if self.task is None or self.task.done():
            self.task = asyncio.create_task(self._announce(), name="speech-recovery")

    async def _announce(self) -> None:
        while self.pending is not None and not self.closed:
            count, limit = self.pending
            self.pending = None
            final = count >= limit
            message = (
                "My speech recognition is still unavailable, so I need to disconnect."
                if final else "I didn't catch that, my speech recognition dropped. Please try again."
            )
            try:
                await self.session.say(message, allow_interruptions=not final).wait_for_playout()
            except Exception:
                logging.getLogger(__name__).exception("speech recognition failure announcement failed")
            if final:
                self.pending = None
                self.session.shutdown(drain=True)
                return

    async def aclose(self) -> None:
        self.closed = True
        self.pending = None
        if self.task is not None and self.task is not asyncio.current_task():
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
