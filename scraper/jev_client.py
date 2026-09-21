"""Temporary Python Jev client until golems' shared ``jev.py`` lands.

The API boundary is shadow-first, requires a sanitizer, and never persists raw state.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Literal, Mapping, Sequence
from urllib.request import Request, urlopen

QuestionType = Literal["noul", "choice", "score"]
Transport = Callable[[dict[str, object], str], Mapping[str, object]]
DEFAULT_LOG = Path("~/.local/state/jev/decisions.jsonl").expanduser()
DEFAULT_USAGE = Path("~/.local/state/jev/usage.jsonl").expanduser()
API_URL = "https://api.typesafe.ai/v1/systemone"


class JevError(RuntimeError):
    """A sanitized Jev boundary failure."""


@dataclass(frozen=True)
class Question:
    id: str
    type: QuestionType
    instructions: object
    criteria: object | None
    fallback: object


@dataclass(frozen=True)
class JevAnswer:
    question_id: str
    type: QuestionType
    answer: object
    confidence: float
    probabilities: Mapping[str, float]
    acted: bool
    model: str
    fallback_used: bool = False
    called: bool = False
    cost_usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0


def hash_state(state: object) -> str:
    encoded = json.dumps(
        state, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _site_mode(site: str) -> str:
    suffix = re.sub(r"[^A-Za-z0-9]", "_", site).upper()
    mode = os.getenv(f"JEV_SITE_{suffix}", "shadow").lower()
    if mode not in {"off", "shadow", "on"}:
        raise JevError("invalid Jev site mode")
    return mode


def _api_key() -> str:
    key = os.getenv("TYPESAFE_API_KEY") or os.getenv("JEV_API_KEY")
    if key:
        return key.strip()
    path = Path("~/.config/typesafe/api-key").expanduser()
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise JevError("Jev API key is unavailable") from exc


def _append(path: Path, row: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _spent_today(path: Path, day: str) -> float:
    if not path.exists():
        return 0.0
    total = 0.0
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if str(row.get("ts", "")).startswith(day):
            total += float(row.get("cost_usd", 0.0))
    return total


def estimate_cost(state: object, question: Question) -> float:
    payload_bytes = len(
        json.dumps([state, question.__dict__], ensure_ascii=False).encode()
    )
    conservative_tokens = max(2048, payload_bytes + 1024)
    return (
        conservative_tokens * float(os.getenv("JEV_USD_PER_MTOK", "0.042")) / 1_000_000
    )


def _http_transport(payload: dict[str, object], api_key: str) -> Mapping[str, object]:
    request = Request(
        API_URL,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urlopen(request, timeout=30) as response:  # noqa: S310 - fixed HTTPS endpoint
        decoded = json.loads(response.read().decode("utf-8"))
    if not isinstance(decoded, dict):
        raise JevError("Jev returned a non-object response")
    return decoded


def _fallbacks(
    state_hash: str, questions: Sequence[Question], site: str, log_path: Path, ts: str
) -> list[JevAnswer]:
    rows = []
    for question in questions:
        _append(
            log_path,
            {
                "ts": ts,
                "site": site,
                "state_hash": state_hash,
                "question_id": question.id,
                "answer": question.fallback,
                "confidence": 0.0,
                "fallback_answer": question.fallback,
                "acted": False,
            },
        )
        rows.append(
            JevAnswer(
                question.id,
                question.type,
                question.fallback,
                0.0,
                {},
                False,
                "fallback",
                True,
            )
        )
    return rows


def jev(
    state: object,
    questions: Sequence[Question],
    *,
    site: str,
    sanitizer: Callable[[object], object],
    transport: Transport | None = None,
    log_path: Path = DEFAULT_LOG,
    usage_path: Path = DEFAULT_USAGE,
) -> list[JevAnswer]:
    """Evaluate exactly one item, with caller-owned sanitization and fallback."""

    if len(questions) != 1:
        raise ValueError("Jev requires exactly one item per call")
    sanitized = sanitizer(state)
    state_digest = hash_state(sanitized)
    now = datetime.now(timezone.utc)
    ts = now.isoformat()
    mode = _site_mode(site)
    if os.getenv("JEV_ENABLED", "1") == "0" or mode == "off":
        return _fallbacks(state_digest, questions, site, log_path, ts)

    cap = float(os.getenv("JEV_DAILY_USD_CAP", "1"))
    reserve = estimate_cost(sanitized, questions[0])
    if _spent_today(usage_path, now.date().isoformat()) + reserve > cap:
        return _fallbacks(state_digest, questions, site, log_path, ts)

    question = questions[0]
    body: dict[str, object] = {
        "type": question.type,
        "instructions": question.instructions,
    }
    if question.criteria is not None:
        body["criteria"] = question.criteria
    payload = {
        "state": sanitized,
        "model": "jev-latest",
        "questions": {question.id: body},
    }
    call = transport or _http_transport
    try:
        raw = call(
            payload,
            _api_key() if transport is None else os.getenv("TYPESAFE_API_KEY", ""),
        )
        answer_raw = raw["answers"]  # type: ignore[index]
        item = answer_raw[question.id]  # type: ignore[index]
        answer_type = str(item["type"])
        if answer_type != question.type:
            raise ValueError("answer type mismatch")
        if question.type == "choice":
            answer = item["choice"]
            confidence = float(item["confidence"])
        elif question.type == "score":
            answer = float(item["score"])
            confidence = float(item["confidence"])
        else:
            answer = float(item["noul"])
            confidence = abs((2 * float(answer)) - 1)
        probabilities = {
            str(k): float(v) for k, v in item.get("probabilities", {}).items()
        }
        usage = raw.get("usage", {})
        input_tokens = int(usage.get("input_tokens", 0))
        output_tokens = int(usage.get("output_tokens", 0))
        cost = (
            (input_tokens + output_tokens)
            * float(os.getenv("JEV_USD_PER_MTOK", "0.042"))
            / 1_000_000
        )
        model = str(raw.get("model", "unknown"))
    except Exception:
        _fallbacks(state_digest, questions, site, log_path, ts)
        raise JevError("Jev request or response validation failed") from None

    acted = mode == "on"
    _append(
        log_path,
        {
            "ts": ts,
            "site": site,
            "state_hash": state_digest,
            "question_id": question.id,
            "answer": answer,
            "confidence": confidence,
            "fallback_answer": question.fallback,
            "acted": acted,
        },
    )
    _append(
        usage_path,
        {
            "ts": ts,
            "site": site,
            "model": model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost_usd": cost,
        },
    )
    return [
        JevAnswer(
            question.id,
            question.type,
            answer,
            confidence,
            probabilities,
            acted,
            model,
            False,
            True,
            cost,
            input_tokens,
            output_tokens,
        )
    ]


def vote_most_cautious(
    call: Callable[[], JevAnswer], *, cautious: object, n: int = 3
) -> JevAnswer:
    """Return the most cautious answer observed across independent calls."""

    if n < 1:
        raise ValueError("n must be positive")
    answers = [call() for _ in range(n)]
    cautious_rows = [answer for answer in answers if answer.answer == cautious]
    if cautious_rows:
        return max(cautious_rows, key=lambda answer: answer.confidence)
    return max(answers, key=lambda answer: answer.confidence)
