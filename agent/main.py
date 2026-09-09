import asyncio
import json
import logging
import os
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path
from uuid import uuid4

from coach import AGENT_NAME, JobCoach
from db import close_pool
from livekit import agents
from livekit.agents import AgentServer, AgentSession
from livekit.agents.metrics import LLMMetrics, TTSMetrics
from livekit.plugins import openai, silero
from qa_receipt import QaStartupReceipt
from stt_whisper import WhisperCppSTT
from speech_recovery import SpeechRecovery
from tools import (
    JobFilters,
    Posting,
    SessionState,
    list_jobs,
    list_new_for_me,
    owner_state_fingerprint,
)
from user import User

_STANDARD_LOG_RECORD_KEYS = frozenset(
    logging.LogRecord("", 0, "", 0, "", (), None).__dict__
) | {"asctime", "message"}


class JsonExtraFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        payload.update(
            {
                key: value
                for key, value in record.__dict__.items()
                if key not in _STANDARD_LOG_RECORD_KEYS
            }
        )
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def _durable_log_path() -> Path:
    default = Path.home() / ".local/state/jobRadarCoach/agent/agent.jsonl"
    configured = Path(
        os.environ.get("AGENT_DURABLE_LOG_FILE", str(default))
    ).expanduser()
    resolved = configured.resolve(strict=False)
    if ".run-state" in resolved.parts:
        logging.getLogger(__name__).warning(
            "AGENT_DURABLE_LOG_FILE points inside disposable run state; using default",
            extra={"rejected_log_path": str(configured), "fallback_log_path": str(default)},
        )
        return default
    return configured


def _add_json_file_handler(root: logging.Logger, path: Path, *, durable: bool) -> None:
    resolved = path.resolve(strict=False)
    for handler in root.handlers:
        if getattr(handler, "_job_radar_log_path", None) == resolved:
            handler.setLevel(logging.DEBUG)
            return
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    file_handler = RotatingFileHandler(path, maxBytes=2_000_000, backupCount=3)
    os.chmod(path, 0o600)
    file_handler._job_radar_file_handler = True  # type: ignore[attr-defined]
    file_handler._job_radar_log_path = resolved  # type: ignore[attr-defined]
    file_handler._job_radar_durable = durable  # type: ignore[attr-defined]
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(JsonExtraFormatter())
    root.addHandler(file_handler)


def setup_logging() -> None:
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    logging.getLogger("livekit.agents").setLevel(logging.DEBUG)
    durable = _durable_log_path()
    _add_json_file_handler(root, durable, durable=True)
    transient = Path(os.environ.get("AGENT_LOG_FILE", "docs.local/agent.log"))
    if transient.resolve(strict=False) != durable.resolve(strict=False):
        _add_json_file_handler(root, transient, durable=False)


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().casefold() in {"1", "true", "yes", "on"}


def _dispatch_metadata(ctx: agents.JobContext) -> dict[str, object]:
    raw = getattr(ctx.job, "metadata", "")
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        logging.getLogger(__name__).warning("invalid dispatch metadata ignored")
        return {}
    return payload if isinstance(payload, dict) else {}


def _rpc_destination(ctx: agents.JobContext) -> tuple[str | None, str]:
    metadata = _dispatch_metadata(ctx)
    configured = metadata.get("web_participant_identity")
    if isinstance(configured, str) and configured.strip():
        return configured.strip(), "dispatch_metadata"
    participants = list(ctx.room.remote_participants.values())
    if len(participants) == 1:
        return participants[0].identity, "sole_remote_participant"
    return None, "ambiguous_remote_participants"


async def _open_job(ctx: agents.JobContext, posting: Posting) -> str:
    request_id = str(uuid4())
    request = {
        "version": 1,
        "request_id": request_id,
        "posting_id": str(posting.id),
        "apply_url": posting.apply_url,
    }
    destination, destination_source = _rpc_destination(ctx)
    arguments = {
        "destination_identity": destination,
        "destination_source": destination_source,
        "method": "jobradar.open_job.v1",
        "payload": request,
    }
    started = time.perf_counter()
    started_at = time.time()
    logger = logging.getLogger(__name__)
    logger.info(
        "tool invocation started",
        extra={
            "tool_name": "open_job",
            "arguments": arguments,
            "start_time": started_at,
        },
    )
    try:
        if destination is None:
            raise RuntimeError("open_job requires one unambiguous web participant")
        raw_ack = await ctx.room.local_participant.perform_rpc(
            destination_identity=destination,
            method="jobradar.open_job.v1",
            payload=json.dumps(request, separators=(",", ":")),
            response_timeout=float(os.environ.get("OPEN_JOB_RPC_TIMEOUT", "5.0")),
        )
        ack = json.loads(raw_ack)
        if not isinstance(ack, dict):
            raise ValueError("open_job acknowledgement is not an object")
        if ack.get("version") != 1 or ack.get("request_id") != request_id:
            raise ValueError("open_job acknowledgement does not match request")
        status = ack.get("status")
        if status not in {"opened", "popup_blocked", "rejected"}:
            raise ValueError("open_job acknowledgement has unsupported status")
        logger.info(
            "tool invocation completed",
            extra={
                "tool_name": "open_job",
                "arguments": arguments,
                "start_time": started_at,
                "duration_ms": round((time.perf_counter() - started) * 1000, 3),
                "outcome": status,
                "acknowledgement": ack,
            },
        )
        if status == "opened":
            return "The browser confirmed that it opened the grounded application page."
        if status == "popup_blocked":
            return "The browser blocked the tab, so the grounded link is on screen for you to tap."
        return (
            "The browser rejected the request, so I couldn't confirm that the job opened. "
            f"The grounded link is {posting.apply_url}."
        )
    except Exception:
        logger.exception(
            "tool invocation failed",
            extra={
                "tool_name": "open_job",
                "arguments": arguments,
                "start_time": started_at,
                "duration_ms": round((time.perf_counter() - started) * 1000, 3),
                "outcome": "exception",
            },
        )
        return (
            "I couldn't confirm that the job opened. The grounded link is "
            f"{posting.apply_url}."
        )


def wire_observability(session: AgentSession, state: SessionState) -> None:
    logger = logging.getLogger(__name__)

    @session.on("conversation_item_added")
    def remember_discussed(event) -> None:
        if getattr(event.item, "role", None) == "assistant":
            spoken_text = event.item.raw_text_content or ""
            state.observe_delivery(spoken_text, interrupted=event.item.interrupted)
            logger.info(
                "assistant delivery completed",
                extra={
                    "intended_text": state.intended_text,
                    "spoken_text": spoken_text,
                    "interrupted": event.item.interrupted,
                    "grounded_posting_id": (
                        str(state.turn_posting.id) if state.turn_posting else None
                    ),
                },
            )

    @session.on("error")
    def record_component_failure(event) -> None:
        wrapped = getattr(event, "error", event)
        error = getattr(wrapped, "error", wrapped)
        recoverable = bool(getattr(wrapped, "recoverable", False))
        logger.log(
            logging.WARNING if recoverable else logging.ERROR,
            "agent session component failure",
            extra={
                "source": type(getattr(event, "source", None)).__name__,
                "recoverable": recoverable,
                "exception_type": type(error).__name__,
                "exception_message": str(error),
            },
            exc_info=(type(error), error, error.__traceback__)
            if isinstance(error, BaseException)
            else None,
        )

    @session.on("close")
    def record_session_close(event) -> None:
        wrapped = getattr(event, "error", None)
        error = getattr(wrapped, "error", wrapped)
        details = {
            "reason": str(getattr(event, "reason", "unknown")),
            "exception_type": type(error).__name__ if error is not None else None,
            "exception_message": str(error) if error is not None else None,
        }
        if error is None:
            logger.info("agent session closed", extra=details)
        else:
            logger.error(
                "agent session closed with error",
                extra=details,
                exc_info=(type(error), error, error.__traceback__)
                if isinstance(error, BaseException)
                else None,
            )

    @session.on("metrics_collected")
    def record_stage_timing(event) -> None:
        metrics = event.metrics
        if isinstance(metrics, LLMMetrics):
            logger.info(
                "model stage completed",
                extra={
                    "stage": "model",
                    "duration_ms": round(metrics.duration * 1000, 3),
                    "time_to_first_token_ms": round(metrics.ttft * 1000, 3),
                    "cancelled": metrics.cancelled,
                    "speech_id": metrics.speech_id,
                },
            )
        elif isinstance(metrics, TTSMetrics):
            logger.info(
                "text-to-speech stage completed",
                extra={
                    "stage": "tts",
                    "duration_ms": round(metrics.duration * 1000, 3),
                    "time_to_first_byte_ms": round(metrics.ttfb * 1000, 3),
                    "audio_duration_ms": round(metrics.audio_duration * 1000, 3),
                    "cancelled": metrics.cancelled,
                    "speech_id": metrics.speech_id,
                },
            )


def register_ping_rpc(ctx: agents.JobContext) -> None:
    """Register the liveness ping. MUST be called after the room is connected —
    local_participant does not exist before that, and touching it raises."""

    def ping(_invocation) -> str:
        return "pong"

    try:
        ctx.room.local_participant.register_rpc_method("jrc.ping", ping)
    except Exception:
        logging.getLogger(__name__).warning(
            "jrc.ping registration failed; liveness probe unavailable", exc_info=True
        )


def interruption_options(stt) -> dict[str, float | int]:
    # Batch Whisper has no words until end-of-speech. Requiring a word here
    # prevents barge-in while the user is still speaking. Silero's sustained
    # speech-duration floor remains the noise gate; explicit overrides survive.
    default_words = "1" if stt.capabilities.interim_results else "0"
    return {
        "min_duration": float(os.environ.get("MIN_INTERRUPTION_DURATION", "0.75")),
        "min_words": int(os.environ.get("MIN_INTERRUPTION_WORDS", default_words)),
    }


async def entrypoint(ctx: agents.JobContext):
    setup_logging()
    logger = logging.getLogger(__name__)
    state = SessionState(qa_mode=_env_flag("VOICE_QA_MODE"))
    before_owner_state: dict[str, object] | None = None
    recovery: SpeechRecovery | None = None
    if state.qa_mode:
        before_owner_state = await owner_state_fingerprint()
        logger.info(
            "voice QA owner state captured",
            extra={
                "voice_qa_mode": True,
                "phase": "before",
                "owner_state": before_owner_state,
                "mutation_capabilities_registered": [],
            },
        )

    async def shutdown() -> None:
        if recovery is not None:
            await recovery.aclose()
        try:
            if state.qa_mode:
                after_owner_state = await owner_state_fingerprint()
                unchanged = after_owner_state == before_owner_state
                logger.log(
                    logging.INFO if unchanged else logging.ERROR,
                    "voice QA owner state verified",
                    extra={
                        "voice_qa_mode": True,
                        "phase": "after",
                        "owner_state": after_owner_state,
                        "owner_state_unchanged": unchanged,
                        "owner_mutations_performed": 0,
                    },
                )
        finally:
            await close_pool()

    ctx.add_shutdown_callback(shutdown)
    try:
        user = await User.load()
    except Exception:
        logging.getLogger(__name__).exception("user profile lookup failed")
        user = User.default()
    try:
        state.load_candidates(
            await list_new_for_me(
                limit=int(os.environ.get("JOB_CANDIDATE_LIMIT", "20")),
                min_score=int(os.environ.get("JOB_MIN_SCORE", "40")),
                excluded_ids=state.discussed_posting_ids,
            )
        )
    except Exception:
        state.fail_lookup()
    logger.info(
        "serialized candidate handoff initialized",
        extra={
            "candidate_count": len(state.candidates),
            "candidate_ids": [str(posting.id) for posting in state.candidates],
            "cursor": state.cursor,
            "voice_qa_mode": state.qa_mode,
        },
    )
    whisper = WhisperCppSTT()
    session = AgentSession(
        userdata=state,
        vad=silero.VAD.load(),
        stt=whisper,
        llm=openai.LLM(
            base_url=os.environ.get("LLM_BASE_URL", "http://127.0.0.1:11434/v1"),
            api_key="none",
            model=os.environ.get("LLM_MODEL", "qwen2.5:7b-instruct"),
            timeout=float(os.environ.get("LLM_TIMEOUT", "60")),
            max_retries=int(os.environ.get("LLM_HTTP_RETRIES", "0")),
        ),
        tts=openai.TTS(
            base_url=os.environ.get("TTS_BASE_URL", "http://127.0.0.1:8881/v1"),
            api_key="none",
            model=os.environ.get("TTS_MODEL", "kokoro"),
            voice=os.environ.get("TTS_VOICE", "af_heart"),
        ),
        use_tts_aligned_transcript=True,
        turn_handling={
            "endpointing": {
                "min_delay": float(os.environ.get("MIN_ENDPOINTING_DELAY", "1.2")),
                "max_delay": float(os.environ.get("MAX_ENDPOINTING_DELAY", "6.0")),
            },
            "interruption": interruption_options(whisper),
        },
    )

    recovery = SpeechRecovery(session)
    whisper.set_failure_handler(recovery.notify)

    wire_observability(session, state)

    await session.start(
        agent=JobCoach(
            user,
            open_job=lambda posting: _open_job(ctx, posting),
            find_jobs=lambda filters: list_jobs(
                limit=int(os.environ.get("JOB_CANDIDATE_LIMIT", "20")),
                filters=JobFilters(
                    location=filters.location,
                    seniority=filters.seniority,
                    min_score=(
                        filters.min_score
                        if filters.min_score is not None
                        else int(os.environ.get("JOB_MIN_SCORE", "40"))
                    ),
                    query=filters.query,
                    remote=filters.remote,
                ),
                excluded_ids=state.discussed_posting_ids,
            ),
        ),
        room=ctx.room,
    )
    # after the room is connected: local_participant now exists
    register_ping_rpc(ctx)
    greeting = (
        f"Hello {user.first_name}. I'm {AGENT_NAME}. "
        "Would you like to hear your strongest new job match?"
    )
    state.intended_text = greeting
    await session.say(greeting, allow_interruptions=True).wait_for_playout()


async def guarded_entrypoint(ctx: agents.JobContext) -> None:
    setup_logging()
    try:
        await entrypoint(ctx)
    except asyncio.CancelledError:
        logging.getLogger(__name__).info("voice agent entrypoint cancelled")
        raise
    except BaseException:
        logging.getLogger(__name__).exception("voice agent entrypoint failed")
        raise


if __name__ == "__main__":
    startup_receipt = QaStartupReceipt()
    server = AgentServer.from_server_options(
        agents.WorkerOptions(
            entrypoint_fnc=guarded_entrypoint,
            agent_name=os.environ.get("LIVEKIT_AGENT_NAME", ""),
            # A worker refuses jobs when host load exceeds this. The default (~0.75 per CPU)
            # silently declines dispatch on a busy Mac, which looks like "agent never joined".
            load_threshold=startup_receipt.worker_load_threshold,
        )
    )
    startup_receipt.bind_registration(
        server=server,
        owner_state_fingerprint=owner_state_fingerprint,
    )
    try:
        agents.cli.run_app(server)
    finally:
        startup_receipt.invalidate()
