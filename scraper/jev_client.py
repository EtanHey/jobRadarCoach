"""Temporary Python Jev client until golems' shared ``jev.py`` lands.

The API boundary is shadow-first, requires a sanitizer, and never persists raw state.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import math
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
MAX_REQUEST_TOKENS = 64_000
MODEL = "jev-1.13.0"
MODEL_USD_PER_MTOK = {MODEL: 0.042}
DEFAULT_USD_PER_MTOK = MODEL_USD_PER_MTOK[MODEL]

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
    encoded = json.dumps(state, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
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
    try:
        return Path("~/.config/typesafe/api-key").expanduser().read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise JevError("Jev API key is unavailable") from exc

def _append(path: Path, row: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")

def _money_rate() -> float:
    try:
        rate = float(os.getenv("JEV_USD_PER_MTOK", str(DEFAULT_USD_PER_MTOK)))
    except ValueError as exc:
        raise JevError("invalid Jev price") from exc
    if not math.isfinite(rate) or rate < DEFAULT_USD_PER_MTOK:
        raise JevError("invalid Jev price")
    return rate

def maximum_call_cost() -> float:
    """Return the documented maximum billed cost of one Jev request."""

    return MAX_REQUEST_TOKENS * _money_rate() / 1_000_000

def estimate_cost(state: object, question: Question) -> float:
    """Estimate input cost for planning; never use this as the hard-cap reservation."""

    payload_bytes = len(json.dumps([state, question.__dict__], ensure_ascii=False).encode())
    conservative_tokens = min(MAX_REQUEST_TOKENS, max(2048, payload_bytes + 1024))
    return conservative_tokens * _money_rate() / 1_000_000

def _ledger_total(handle, day: str) -> float:
    handle.seek(0)
    total = 0.0
    for line in handle:
        try:
            row = json.loads(line)
            if str(row.get("ts", "")).startswith(day):
                total += float(row.get("cost_usd", 0.0))
        except (json.JSONDecodeError, TypeError, ValueError):
            continue
    return total

def _ledger_entry(handle, row: Mapping[str, object]) -> None:
    handle.seek(0, os.SEEK_END)
    handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    handle.flush()
    os.fsync(handle.fileno())

def _reserve(usage_path: Path, *, cap: float, ts: str, site: str) -> float | None:
    reserve = maximum_call_cost()
    usage_path.parent.mkdir(parents=True, exist_ok=True)
    with usage_path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        if _ledger_total(handle, ts[:10]) + reserve > cap:
            return None
        _ledger_entry(handle, {"ts": ts, "site": site, "kind": "reservation", "cost_usd": reserve})
    return reserve

def _reconcile(usage_path: Path, *, reserved: float, actual: float, row: Mapping[str, object]) -> None:
    with usage_path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        _ledger_entry(handle, {**row, "kind": "reconciliation", "cost_usd": actual - reserved})

def _http_transport(payload: dict[str, object], api_key: str) -> Mapping[str, object]:
    request = Request(
        API_URL,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=30) as response:  # noqa: S310 - fixed HTTPS endpoint
        decoded = json.loads(response.read().decode("utf-8"))
    if not isinstance(decoded, dict):
        raise JevError("Jev returned a non-object response")
    return decoded

def _fallbacks(state_hash: str, questions: Sequence[Question], site: str, log_path: Path, ts: str, *,
               called: bool = False, model: str = "fallback", cost_usd: float = 0.0,
               input_tokens: int = 0, output_tokens: int = 0) -> list[JevAnswer]:
    rows = []
    for question in questions:
        _append(log_path, {"ts": ts, "site": site, "state_hash": state_hash, "question_id": question.id,
                           "answer": question.fallback, "confidence": 0.0, "fallback_answer": question.fallback,
                           "acted": False})
        rows.append(JevAnswer(question.id, question.type, question.fallback, 0.0, {}, False, model, True, called,
                              cost_usd, input_tokens, output_tokens))
    return rows

def _number(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"invalid {field}")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"invalid {field}")
    return number

def _probabilities(item: Mapping[str, object], expected: set[str]) -> dict[str, float]:
    raw = item["probabilities"]
    if not isinstance(raw, Mapping) or set(raw) != expected:
        raise ValueError("invalid probability keys")
    values = {str(key): _number(value, "probability") for key, value in raw.items()}
    if any(value < 0 or value > 1 for value in values.values()) or not math.isclose(sum(values.values()), 1.0, abs_tol=1e-6):
        raise ValueError("invalid probabilities")
    return values

def _usage(raw: Mapping[str, object]) -> tuple[int, int]:
    if not isinstance(raw, Mapping):
        raise ValueError("invalid response")
    usage = raw.get("usage")
    if not isinstance(usage, Mapping):
        raise ValueError("invalid usage")
    input_tokens, output_tokens = usage.get("input_tokens"), usage.get("output_tokens")
    if isinstance(input_tokens, bool) or isinstance(output_tokens, bool) or not isinstance(input_tokens, int) or not isinstance(output_tokens, int):
        raise ValueError("invalid usage")
    if not 0 <= input_tokens <= MAX_REQUEST_TOKENS or output_tokens < 0:
        raise ValueError("invalid usage")
    return input_tokens, output_tokens

def _parse_response(raw: Mapping[str, object], question: Question) -> tuple[object, float, dict[str, float], str, int, int]:
    if not isinstance(raw, Mapping) or not isinstance(raw.get("model"), str) or not raw["model"]:
        raise ValueError("invalid response")
    answers = raw.get("answers")
    if not isinstance(answers, Mapping) or set(answers) != {question.id}:
        raise ValueError("invalid answers")
    item = answers[question.id]
    if not isinstance(item, Mapping) or item.get("type") != question.type:
        raise ValueError("answer type mismatch")
    if question.type == "choice":
        if not isinstance(question.criteria, Mapping) or not question.criteria:
            raise ValueError("invalid choice criteria")
        options = {str(key) for key in question.criteria}
        answer = item["choice"]
        if not isinstance(answer, str) or answer not in options:
            raise ValueError("unknown choice")
        confidence = _number(item["confidence"], "confidence")
        probabilities = _probabilities(item, options)
        if probabilities[answer] != max(probabilities.values()):
            raise ValueError("choice is not highest probability")
    elif question.type == "score":
        if not isinstance(question.criteria, Sequence) or isinstance(question.criteria, (str, bytes)) or len(question.criteria) < 2:
            raise ValueError("invalid score criteria")
        answer = _number(item["score"], "score")
        if answer < 0 or answer > len(question.criteria) - 1:
            raise ValueError("invalid score")
        confidence = _number(item["confidence"], "confidence")
        levels = {str(index) for index in range(len(question.criteria))}
        legend = item["legend"]
        if not isinstance(legend, Mapping) or set(legend) != levels or any(
            legend[str(index)] != value for index, value in enumerate(question.criteria)
        ):
            raise ValueError("invalid score legend")
        probabilities = _probabilities(item, levels)
        expected_score = sum(int(level) * probability for level, probability in probabilities.items())
        if not math.isclose(answer, expected_score, abs_tol=1e-6):
            raise ValueError("score does not match probabilities")
    else:
        answer = _number(item["noul"], "noul")
        confidence = abs((2 * answer) - 1)
        probabilities = {}
    if not 0 <= confidence <= 1 or question.type == "noul" and not 0 <= float(answer) <= 1:
        raise ValueError("answer outside range")
    input_tokens, output_tokens = _usage(raw)
    return answer, confidence, probabilities, str(raw["model"]), input_tokens, output_tokens

def jev(state: object, questions: Sequence[Question], *, site: str, sanitizer: Callable[[object], object],
        transport: Transport | None = None, log_path: Path = DEFAULT_LOG, usage_path: Path = DEFAULT_USAGE) -> list[JevAnswer]:
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
    if not math.isfinite(cap) or cap < 0:
        raise JevError("invalid Jev daily cap")
    reserved = _reserve(usage_path, cap=cap, ts=ts, site=site)
    if reserved is None:
        return _fallbacks(state_digest, questions, site, log_path, ts)

    question = questions[0]
    body: dict[str, object] = {"type": question.type, "instructions": question.instructions}
    if question.criteria is not None:
        body["criteria"] = question.criteria
    payload = {"state": sanitized, "model": MODEL, "questions": {question.id: body}}
    call = transport or _http_transport
    called = False
    try:
        api_key = _api_key()
        called = True
        raw = call(payload, api_key)
        answer, confidence, probabilities, model, input_tokens, output_tokens = _parse_response(raw, question)
    except Exception:
        if not called:
            return _fallbacks(state_digest, questions, site, log_path, ts)
        try:
            input_tokens, output_tokens = _usage(raw)
        except (TypeError, ValueError, UnboundLocalError):
            return _fallbacks(state_digest, questions, site, log_path, ts, called=True)
        model = str(raw["model"]) if isinstance(raw.get("model"), str) and raw["model"] else "fallback"
        cost = input_tokens * _money_rate() / 1_000_000
        _reconcile(usage_path, reserved=reserved, actual=cost,
                   row={"ts": ts, "site": site, "model": model,
                        "input_tokens": input_tokens, "output_tokens": output_tokens})
        return _fallbacks(state_digest, questions, site, log_path, ts, called=True, model=model,
                          cost_usd=cost, input_tokens=input_tokens, output_tokens=output_tokens)

    cost = input_tokens * _money_rate() / 1_000_000
    _reconcile(usage_path, reserved=reserved, actual=cost,
               row={"ts": ts, "site": site, "model": model, "input_tokens": input_tokens, "output_tokens": output_tokens})
    acted = mode == "on"
    _append(log_path, {"ts": ts, "site": site, "state_hash": state_digest, "question_id": question.id,
                       "answer": answer, "confidence": confidence, "fallback_answer": question.fallback, "acted": acted})
    return [JevAnswer(question.id, question.type, answer, confidence, probabilities, acted, model, False, True,
                      cost, input_tokens, output_tokens)]

def vote_most_cautious(call: Callable[[], JevAnswer], *, cautious: object, n: int = 3) -> JevAnswer:
    """Return the most cautious answer observed across independent calls."""

    if n < 1:
        raise ValueError("n must be positive")
    answers = [call() for _ in range(n)]
    cautious_rows = [answer for answer in answers if answer.answer == cautious]
    return max(cautious_rows or answers, key=lambda answer: answer.confidence)
