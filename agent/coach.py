import asyncio
import logging
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

SAY_AS = {
    "Tel Aviv": "Tell Aveev",
    "Jeen": "Jeen",
}

AGENT_NAME = "Riki"

_NEXT_RE = re.compile(r"\b(next|another|different|more)\b", re.IGNORECASE)
_LINK_RE = re.compile(r"\b(link|url|apply|application page)\b", re.IGNORECASE)
_OPEN_RE = re.compile(
    r"\b(open(?: it| this| the job| the application| the link)?|"
    r"show (?:it|this) in (?:a )?browser)\b",
    re.IGNORECASE,
)
_DECLINE_RE = re.compile(r"\b(no|not now|don't|do not)\b", re.IGNORECASE)
_JOB_RE = re.compile(
    r"\b(yes|yeah|sure|okay|ok|job|match|role|position|opportunit(?:y|ies)|hear|show|find|recommend)\b",
    re.IGNORECASE,
)
_OUT_OF_SCOPE_RE = re.compile(
    r"\b(cake|recipe|weather|news|medical|health advice|internet search|browse the web)\b",
    re.IGNORECASE,
)
_URL_RE = re.compile(r"https?://[^\s)\]>]+")
_CLEAR_FILTERS_RE = re.compile(
    r"\b(clear|remove|reset)\b.{0,30}\b(filters?|constraints?)\b|\bshow me everything\b",
    re.IGNORECASE,
)
_LOCATION_RE = re.compile(
    r"\b(?:jobs?|roles?|positions?|opportunit(?:y|ies)|something)\s+"
    r"(?:located\s+|based\s+)?in\s+"
    r"(?P<location>[A-Za-z][A-Za-z .'-]{1,50}?)"
    r"(?=\s+(?:with|using|above|over|at least|scor(?:e|ed)|and)\b|[?!,.]|$)",
    re.IGNORECASE,
)
_LOCATION_IS_RE = re.compile(
    r"\b(?:location|country|city)\s+(?:is|of|to)\s+"
    r"(?P<location>[A-Za-z][A-Za-z .'-]{1,50}?)(?=[?!,.]|$)",
    re.IGNORECASE,
)
_REMOTE_RE = re.compile(r"\b(remote|work(?:ing)? from home|wfh)\b", re.IGNORECASE)
_ONSITE_RE = re.compile(r"\b(on[ -]?site|not remote)\b", re.IGNORECASE)
_SENIORITY_RE = re.compile(
    r"\b(intern(?:ship)?|junior|entry(?: level)?|mid(?: level)?|senior|staff|principal|lead)\b",
    re.IGNORECASE,
)
_SCORE_PREFIX_RE = re.compile(
    r"\b(?:score|scored)\s*(?:of|at least|above|over|greater than)?\s*"
    r"(?P<score>\d{1,3})\b",
    re.IGNORECASE,
)
_SCORE_SUFFIX_RE = re.compile(
    r"\b(?:at least|above|over|greater than)\s*(?P<score>\d{1,3})\s*"
    r"(?:score|points?)\b",
    re.IGNORECASE,
)
_QUERY_CUE_RE = re.compile(
    r"\b(?:using|with|stack(?: of)?|technology|tech)\s+"
    r"(?:a\s+|an\s+)?(?P<query>[A-Za-z][A-Za-z0-9.+#/-]{0,29})\b",
    re.IGNORECASE,
)
_COMMON_QUERY_RE = re.compile(
    r"\b(python|typescript|javascript|react(?:\.js)?|next(?:\.js)?|node(?:\.js)?|"
    r"fastapi|django|rust|golang|kotlin|swift|java|c#|\.net|ruby|rails|postgres(?:ql)?|"
    r"supabase|aws|gcp|azure|kubernetes|docker|terraform|frontend|backend|full[ -]?stack|"
    r"machine learning|artificial intelligence|llm)\b",
    re.IGNORECASE,
)
_logger = logging.getLogger(__name__)


def _clean_constraint(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip(" .,!?:;")


def extract_job_filter_updates(text: str) -> tuple[dict[str, object], bool]:
    """Extract only explicit constraints; never infer job facts or preferences."""
    if _CLEAR_FILTERS_RE.search(text):
        return {}, True

    updates: dict[str, object] = {}
    location_match = _LOCATION_RE.search(text) or _LOCATION_IS_RE.search(text)
    if location_match:
        location = _clean_constraint(location_match.group("location"))
        if location:
            updates["location"] = location

    if _ONSITE_RE.search(text):
        updates["remote"] = False
    elif _REMOTE_RE.search(text):
        updates["remote"] = True

    seniority = _SENIORITY_RE.search(text)
    if seniority:
        value = seniority.group(1).casefold().replace(" ", "_")
        updates["seniority"] = "entry" if value == "entry_level" else value

    score = _SCORE_PREFIX_RE.search(text) or _SCORE_SUFFIX_RE.search(text)
    if score:
        value = int(score.group("score"))
        if 0 <= value <= 100:
            updates["min_score"] = value

    query = _QUERY_CUE_RE.search(text)
    if query is not None and query.group("query").casefold() in {
        "score",
        "minimum",
        "rating",
    }:
        query = None
    if query is None:
        query = _COMMON_QUERY_RE.search(text)
    if query:
        updates["query"] = _clean_constraint(
            query.groupdict().get("query") or query.group(0)
        )

    return updates, False


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
        requested_posting = bool(_JOB_RE.search(text) or _NEXT_RE.search(text))

        filter_updates, clear_filters = extract_job_filter_updates(text)
        if clear_filters or filter_updates:
            filters = JobFilters() if clear_filters else state.filters.merged(filter_updates)
            if self._find_jobs is None:
                state.deterministic_reply = JOB_LOOKUP_FAILED
                return
            try:
                state.replace_candidates(await self._find_jobs(filters), filters=filters)
            except Exception:
                state.fail_lookup()
                state.deterministic_reply = JOB_LOOKUP_FAILED
                return
            _logger.info(
                "spoken job constraints applied",
                extra={
                    "filter_updates": filter_updates,
                    "filters_cleared": clear_filters,
                    "active_filters": filters.as_log_fields(),
                    "candidate_count": len(state.candidates),
                    "candidate_ids": [str(posting.id) for posting in state.candidates],
                    "cursor": state.cursor,
                },
            )
            requested_posting = True
            if not state.candidates:
                state.deterministic_reply = NO_FILTERED_JOBS
                return

        if _OUT_OF_SCOPE_RE.search(text):
            state.deterministic_reply = (
                "I don't have web access for that. I can help with your grounded job matches."
            )
            return

        posting = state.current_posting
        if posting is None:
            if state.lookup_error:
                state.deterministic_reply = JOB_LOOKUP_FAILED
                return
            if state.cursor >= len(state.candidates):
                state.deterministic_reply = NO_MORE_JOBS
                return
            if _DECLINE_RE.search(text) and not _NEXT_RE.search(text):
                state.deterministic_reply = (
                    "Okay. Tell me when you want to hear a grounded job match."
                )
                return
            if requested_posting:
                posting = state.advance(strong_only=not _NEXT_RE.search(text))
        elif _NEXT_RE.search(text):
            posting = state.advance()

        if posting is None:
            if state.cursor >= len(state.candidates):
                state.deterministic_reply = NO_MORE_JOBS
            elif state.cursor == -1 and requested_posting:
                state.deterministic_reply = NO_STRONG_JOBS
            else:
                state.deterministic_reply = (
                    "I can help with the grounded job matches loaded for this conversation."
                )
            return

        if _OPEN_RE.search(text):
            if self._open_job is None:
                state.deterministic_reply = (
                    "I couldn't confirm that the job opened. The grounded link is "
                    f"{posting.apply_url}."
                )
            else:
                state.deterministic_reply = await self._open_job(posting)
            return

        if _LINK_RE.search(text):
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
