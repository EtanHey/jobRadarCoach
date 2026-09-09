import asyncio
import logging
import json
import time
import re
from collections.abc import AsyncIterable, AsyncIterator, Awaitable, Callable

from livekit.agents import Agent, llm
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
from grounded_speech import GroundingError, SPEECH_INSTRUCTIONS, SentenceDecoder, render_sentence
from claim_audit import audit_sentence

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
        self._profile_facts = json.dumps({"positioning": user.positioning, "roles_wanted": user.roles_wanted, "stacks": user.stacks})
        super().__init__(
            tools=[],
            instructions=(
                f"You are {AGENT_NAME}, {user.first_name}'s job-search coach. You talk over voice: "
                "one to three short sentences per reply, no markdown, no lists, no asterisks. "
                f"{user.first_name} is {user.positioning}, wants {', '.join(user.roles_wanted)}, "
                f"works with {', '.join(user.stacks)}.\n"
                "NEVER recommend or name a job from your own knowledge. Application code, not you, "
                "loads real scraped postings and hands you at most one posting per turn. Speak only "
                "about the posting in the current CURRENT_FACTS record. If no posting is supplied, "
                "do not mention any job. Any link you say must be the exact supplied apply_url.\n"
                "Scores: above seventy, recommend applying. Forty to seventy, mention only if asked "
                "for more options. Below forty, say it is not worth it.\n"
                "Walk jobs ONE AT A TIME. Describe one job and why it fits, then stop and wait. "
                "Never list several jobs in one reply.\n"
                "After describing one job, STOP. Do not describe another until he answers.\n"
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
        state.search_widened = False
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
            state.turn_posting = posting
            if self._open_job is None:
                state.deterministic_reply = (
                    "I couldn't confirm that the job opened. The grounded link is "
                    f"{posting.apply_url}."
                )
            else:
                state.deterministic_reply = await self._open_job(posting)
            return

        if intent.action == "link":
            state.turn_posting = posting
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
        posting = state.turn_posting
        facts = ({key: str(value) for key, value in posting.as_log_row().items() if key != "id"} if posting else {})
        if state.deterministic_reply:
            facts["outcome"] = state.deterministic_reply
        elif state.search_widened:
            facts["outcome"] = "The subject query matched no jobs. Code removed only that query, retained the other filters, and found results."
        # Keep only the latest factual handoff, not a trail of competing postings.
        context = chat_ctx.copy()
        context.items = [item for item in context.items if not (
            isinstance(item, llm.ChatMessage) and item.role == "system"
            and (item.text_content or "").startswith(("GROUNDING:", "CURRENT_FACTS:", "SEARCH_RESULT:"))
        )]
        context.add_message(role="system", content=SPEECH_INSTRUCTIONS)
        context.add_message(role="system", content="USER_PROFILE (context, never speak raw JSON): " + self._profile_facts)
        context.add_message(role="system", content="CURRENT_FACTS: " + json.dumps(facts, ensure_ascii=False))
        if state.search_widened:
            context.add_message(role="system", content="Disclose the search widening in outcome once this turn. Do not imply the original subject matched.")
        source = Agent.default.llm_node(self, context, [], model_settings)
        if asyncio.iscoroutine(source):
            source = await source
        decoder = SentenceDecoder()
        started = time.perf_counter()
        raw_text = ""
        delivered = []
        first_token = None
        try:
            if source is None:
                raise GroundingError("model_unavailable")
            async for chunk in source:
                delta = chunk if isinstance(chunk, str) else (
                    chunk.delta.content if isinstance(chunk, llm.ChatChunk) and chunk.delta else None
                )
                if not delta:
                    continue
                if first_token is None:
                    first_token = round((time.perf_counter() - started) * 1000, 3)
                raw_text += delta
                for envelope in decoder.push(delta):
                    speech = render_sentence(envelope, facts)
                    audit_started = time.perf_counter()
                    await self._audit_speech(speech.text, facts, speech.references)
                    delivered.append(speech.text)
                    state.intended_text = " ".join(delivered)
                    _logger.info("grounded speech released", extra={
                        "first_token_ms": first_token,
                        "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
                        "envelope_index": len(delivered), "fact_references": speech.references,
                        "stance": speech.stance, "model_written": True,
                        "claim_audit_ms": round((time.perf_counter() - audit_started) * 1000, 3),
                    })
                    yield speech.text + " "
            decoder.finish()
        except Exception as error:
            _logger.warning("model speech rejected", extra={
                "model_text": raw_text, "reason": str(error),
                "released_envelopes": len(delivered),
            })
            fallback = (
                "I couldn't verify that detail."
                if delivered else state.deterministic_reply or (
                    self._fallback_reply(posting) if posting else
                    "I couldn't put that reply together. Could you try again?"
                )
            )
            delivered.append(fallback)
            state.intended_text = " ".join(delivered)
            yield fallback
        finally:
            if source is not None:
                await source.aclose()
            _logger.info("assistant intended text captured", extra={
                "model_text": raw_text, "intended_text": state.intended_text,
                "grounded_posting_id": str(posting.id) if posting else None,
            })

    async def _audit_speech(self, text: str, facts: dict[str, str], references: tuple[str, ...]) -> None:
        # An independent request sees the rendered proposition, not the writer's
        # declared stance/references. Never release unchecked speech on failure.
        started = time.perf_counter()
        outcome = "cancelled"
        try:
            await audit_sentence(self.session.llm, text, {**facts, "user_profile": self._profile_facts}, expected_references=references)
            outcome = "accepted"
        except Exception:
            outcome = "rejected"
            raise
        finally:
            _logger.info("claim audit completed", extra={
                "duration_ms": round((time.perf_counter() - started) * 1000, 3), "outcome": outcome,
            })

    def _fallback_reply(self, posting: Posting) -> str:
        reason = posting.reasons.split(". ", 1)[0].strip()
        if reason and not reason.endswith("."):
            reason += "."
        location = f" in {posting.location}" if posting.location else ""
        explanation = f" {reason}" if reason else ""
        advice = " I'd recommend a closer look." if posting.score > 70 else (
            " It's a weaker option." if posting.score >= 40 else " I don't think it is worth pursuing."
        )
        return (
            f"{posting.title} at {posting.company}{location} scored {posting.score}."
            f"{explanation}{advice}"
        )

    async def tts_node(self, text: AsyncIterable[str], model_settings):
        # llm_node now emits complete validated speech envelopes. Avoid another
        # sentence buffer before the SDK's TTS adapter sees the first one.
        async def spoken_text() -> AsyncIterator[str]:
            async for chunk in text:
                for written, pronunciation in SAY_AS.items():
                    chunk = chunk.replace(written, pronunciation)
                yield chunk

        async for frame in Agent.default.tts_node(self, spoken_text(), model_settings):
            yield frame
