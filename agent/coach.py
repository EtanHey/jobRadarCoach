import asyncio
import logging
import json
import time
import re
from collections.abc import AsyncIterable, AsyncIterator, Awaitable, Callable

from livekit.agents import Agent, llm, tokenize
from livekit.agents.types import FlushSentinel

from tools import (
    JobFilters,
    JOB_LOOKUP_FAILED,
    NO_FILTERED_JOBS,
    NO_MORE_JOBS,
    NO_STRONG_JOBS,
    Posting,
    SessionState,
)
from user import User
from intent import INTENT_INSTRUCTIONS, Intent, fast_intent, validate_intent

SAY_AS = {
    "Tel Aviv": "Tell Aveev",
    "Jeen": "Jeen",
}

AGENT_NAME = "Riki"

_URL_RE = re.compile(r"https?://[^\s)\]>]+")
_logger = logging.getLogger(__name__)


def extract_job_filter_updates(text: str) -> tuple[dict[str, object], bool]:
    intent = fast_intent(text)
    return (intent.filters, intent.action == "clear") if intent else ({}, False)


class JobCoach(Agent):
    def __init__(
        self,
        user: User,
        *,
        open_job: Callable[[Posting], Awaitable[str]] | None = None,
        find_jobs: Callable[[JobFilters], Awaitable[list[Posting]]] | None = None,
    ):
        self._open_job = open_job
        self._find_jobs = find_jobs
        super().__init__(
            tools=[],
            instructions=(
                f"You are {AGENT_NAME}, {user.first_name}'s job-search coach. You talk over voice: "
                "one to three short sentences per reply, no markdown, no lists, no asterisks. "
                f"{user.first_name} is {user.positioning}, wants {', '.join(user.roles_wanted)}, "
                f"works with {', '.join(user.stacks)}.\n"
                "NEVER recommend or name a job from your own knowledge. Application code, not you, "
                "loads real scraped postings and hands you at most one posting per turn. Speak only "
                "about the posting in the current GROUNDING record. If there is no GROUNDING record, "
                "do not mention any job. Any link you say must be the exact apply_url in GROUNDING.\n"
                "Scores: above seventy, recommend applying. Forty to seventy, mention only if asked "
                "for more options. Below forty, say it is not worth it.\n"
                "Walk jobs ONE AT A TIME. Describe one job and why it fits, then stop and wait. "
                "Never list several jobs in one reply.\n"
                "After describing one job, ask what he thinks of it and STOP. "
                "Do not describe another until he answers.\n"
                "If a job is a poor fit say so plainly and say why. Do not soften a bad score. "
                "You have no web access. For requests outside job search, say that briefly and steer "
                "back to the job search; never present outside information as fetched fact."
            ),
        )

    @property
    def state(self) -> SessionState:
        return self.session.userdata

    async def on_user_turn_completed(
        self, turn_ctx: llm.ChatContext, new_message: llm.ChatMessage
    ) -> None:
        await self._prepare_turn(turn_ctx, new_message)

    async def _prepare_turn(
        self, turn_ctx: llm.ChatContext, new_message: llm.ChatMessage
    ) -> None:
        text = new_message.text_content or ""
        state = self.state
        state.prepared_message_id = new_message.id
        state.turn_posting = None
        state.deterministic_reply = None
        state.intended_text = None
        intent = await self._resolve_intent(text)
        if intent is None:
            state.deterministic_reply = "I couldn't work out that request. Could you say what you'd like to change?"
            return
        requested_posting = intent.action in {"search", "next", "clear"}
        if intent.more_options:
            state.allow_more_options = True
        if intent.action == "pause":
            state.deterministic_reply = "Okay, I'll wait."
            return
        if intent.action == "clear" or intent.filters:
            state.allow_more_options = intent.more_options
            filters = JobFilters() if intent.action == "clear" else state.filters.merged(intent.filters)
            if self._find_jobs is None:
                state.deterministic_reply = JOB_LOOKUP_FAILED
                return
            try:
                candidates = await self._find_jobs(filters)
                state.search_widened = False
                if not candidates and filters.query:
                    # Keep explicit geography/seniority/score; widen only the subject.
                    wider = filters.merged({"query": None})
                    candidates = await self._find_jobs(wider)
                    if candidates:
                        filters = wider
                        state.search_widened = True
                state.replace_candidates(candidates, filters=filters)
            except Exception:
                state.fail_lookup()
                state.deterministic_reply = JOB_LOOKUP_FAILED
                return
            _logger.info("spoken job constraints applied", extra={
                "filter_updates": intent.filters, "active_filters": filters.as_log_fields(),
                "candidate_count": len(state.candidates), "search_widened": state.search_widened,
            })
            if state.search_widened:
                turn_ctx.add_message(role="system", content="SEARCH_RESULT: No result matched the subject query. Code retried WITHOUT that query, retaining the other filters, and found results. Tell the user plainly that you widened the subject search. Do not claim the original subject matched.")
            if not state.candidates:
                state.deterministic_reply = NO_FILTERED_JOBS
                return

        posting = state.current_posting
        if posting is None:
            if state.lookup_error:
                state.deterministic_reply = JOB_LOOKUP_FAILED
                return
            if state.cursor >= len(state.candidates):
                state.deterministic_reply = NO_MORE_JOBS
                return
            if requested_posting:
                posting = state.advance(strong_only=not state.allow_more_options)
        elif intent.action == "next":
            posting = state.advance(strong_only=not state.allow_more_options)

        if posting is None:
            if state.cursor >= len(state.candidates):
                state.deterministic_reply = NO_MORE_JOBS
            elif requested_posting and not state.allow_more_options:
                state.deterministic_reply = NO_STRONG_JOBS
            else:
                state.deterministic_reply = (
                    "I can help with the grounded job matches loaded for this conversation."
                )
            return

        if intent.action == "open":
            if self._open_job is None:
                state.deterministic_reply = (
                    "I couldn't confirm that the job opened. The grounded link is "
                    f"{posting.apply_url}."
                )
            else:
                state.deterministic_reply = await self._open_job(posting)
            return

        if intent.action == "link":
            state.deterministic_reply = f"The application link I was given is {posting.apply_url}."
            return

        state.turn_posting = posting
        turn_ctx.add_message(
            role="system",
            content=(
                "GROUNDING: The application code selected exactly this one database posting for "
                "the current reply. Use no job facts outside this JSON record, do not infer missing "
                f"facts, and do not mention any other posting. {posting.grounded_context()}"
            ),
        )

    async def _resolve_intent(self, text: str) -> Intent | None:
        started = time.perf_counter()
        try:
            direct = fast_intent(text)
            if direct is not None:
                return direct
            # Follow-up explanations keep the current posting and need only one model pass.
            if self.state.current_posting is not None and re.match(
                r"^\s*(why|how|tell me more about|what (?:does|makes|is))\b", text, re.I
            ):
                return Intent("discuss")
            context = llm.ChatContext.empty()
            context.add_message(role="system", content=INTENT_INSTRUCTIONS)
            context.add_message(role="user", content=text)
            model = self.session.llm
            if model is None:
                return None
            output = ""
            async with asyncio.timeout(8):
                async with model.chat(chat_ctx=context, tools=[], response_format={"type": "json_object"}) as stream:
                    async for chunk in stream:
                        if chunk.delta and chunk.delta.content:
                            output += chunk.delta.content
                            if len(output) > 4096:
                                raise ValueError("intent response too large")
            return validate_intent(json.loads(output), text)
        except Exception as error:
            _logger.warning("intent interpretation rejected", extra={"reason": str(error)})
            return None
        finally:
            _logger.info("intent stage completed", extra={"duration_ms": round((time.perf_counter() - started) * 1000, 3)})

    async def llm_node(
        self,
        chat_ctx: llm.ChatContext,
        tools: list[llm.Tool],
        model_settings,
    ) -> AsyncIterator[llm.ChatChunk | str | FlushSentinel]:
        state = self.state
        latest_user = next(
            (message for message in reversed(chat_ctx.messages()) if message.role == "user"),
            None,
        )
        if latest_user is not None and latest_user.id != state.prepared_message_id:
            await self._prepare_turn(chat_ctx, latest_user)
        if state.deterministic_reply is not None:
            reply = state.deterministic_reply
            state.intended_text = reply
            _logger.info(
                "model call skipped by deterministic guard",
                extra={
                    "stage": "model",
                    "outcome": "skipped",
                    "reason": "deterministic_guard",
                    "intended_text": reply,
                },
            )
            yield reply
            return

        source = Agent.default.llm_node(self, chat_ctx, tools, model_settings)
        if asyncio.iscoroutine(source):
            source = await source
        if source is None:
            return

        posting = state.turn_posting
        if posting is None:
            intended = ""
            try:
                async for chunk in source:
                    if isinstance(chunk, str):
                        intended += chunk
                    elif isinstance(chunk, llm.ChatChunk) and chunk.delta and chunk.delta.content:
                        intended += chunk.delta.content
                    yield chunk
            finally:
                state.intended_text = intended
                _logger.info(
                    "assistant intended text captured",
                    extra={"intended_text": intended, "grounded_posting_id": None},
                )
            return

        model_text = ""
        async for chunk in source:
            if isinstance(chunk, str):
                model_text += chunk
            elif isinstance(chunk, llm.ChatChunk) and chunk.delta and chunk.delta.content:
                model_text += chunk.delta.content

        intended = self._validated_grounded_reply(model_text, posting)
        state.intended_text = intended
        _logger.info(
            "assistant intended text captured",
            extra={
                "model_text": model_text,
                "intended_text": intended,
                "grounded_posting_id": str(posting.id),
                "grounding_guard_changed_output": intended != model_text,
            },
        )
        yield intended

    def _validated_grounded_reply(self, model_text: str, posting: Posting) -> str:
        urls = [url.rstrip(".,") for url in _URL_RE.findall(model_text)]
        wrong_url = any(url != posting.apply_url for url in urls)
        missing_identity = not (
            posting.title.casefold() in model_text.casefold()
            and posting.company.casefold() in model_text.casefold()
        )
        other_candidate = any(
            candidate.id != posting.id
            and (
                candidate.company.casefold() in model_text.casefold()
                or candidate.title.casefold() in model_text.casefold()
            )
            for candidate in self.state.candidates
        )
        asks_for_reaction = "what do you think" in model_text.casefold()
        if (
            model_text.strip()
            and not wrong_url
            and not missing_identity
            and not other_candidate
            and asks_for_reaction
        ):
            return model_text.strip()

        reason = posting.reasons.split(". ", 1)[0].strip()
        if reason and not reason.endswith("."):
            reason += "."
        location = f" in {posting.location}" if posting.location else ""
        explanation = f" {reason}" if reason else ""
        return (
            f"{posting.title} at {posting.company}{location} scored {posting.score}."
            f"{explanation} What do you think of this role?"
        )

    async def tts_node(self, text: AsyncIterable[str], model_settings):
        sentence_stream = tokenize.blingfire.SentenceTokenizer(retain_format=True).stream()

        async def feed_sentences() -> None:
            try:
                async for chunk in text:
                    sentence_stream.push_text(chunk)
                sentence_stream.end_input()
            except BaseException:
                await sentence_stream.aclose()
                raise

        feeder = asyncio.create_task(feed_sentences())

        async def fixed_sentences() -> AsyncIterator[str]:
            try:
                async for sentence in sentence_stream:
                    spoken = sentence.token
                    for written, pronunciation in SAY_AS.items():
                        spoken = spoken.replace(written, pronunciation)
                    yield spoken
            finally:
                await sentence_stream.aclose()

        try:
            async for frame in Agent.default.tts_node(self, fixed_sentences(), model_settings):
                yield frame
        finally:
            if not feeder.done():
                feeder.cancel()
            await asyncio.gather(feeder, return_exceptions=True)
