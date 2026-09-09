"""Validate one model-written natural reply before independent claim audit."""

import json
import re
from dataclasses import dataclass

from claim_audit import GroundingError


@dataclass(frozen=True)
class Speech:
    text: str
    stance: str


_URL_RE = re.compile(r"https?://[^\s)\]>]+", re.I)
_NUMBER_RE = re.compile(r"(?<![\w/])\d+(?:\.\d+)?(?![\w/])")
_NUMERIC_FACTS = (
    "title",
    "company",
    "location",
    "score",
    "reasons",
    "outcome",
    "user_profile",
)


def render_sentence(payload: object, facts: dict[str, str]) -> Speech:
    if not isinstance(payload, dict) or set(payload) != {"sentence", "stance"}:
        raise GroundingError("invalid_speech_fields")
    sentence, stance = payload["sentence"], payload["stance"]
    if not isinstance(stance, str) or stance not in {"neutral", "recommend", "weak_option", "poor_fit"}:
        raise GroundingError("invalid_stance")
    score = facts.get("score")
    allowed = {"neutral"}
    if score is not None:
        allowed.add("recommend" if int(score) > 70 else "weak_option" if int(score) >= 40 else "poor_fit")
    if stance not in allowed:
        raise GroundingError("stance_contradicts_verified_score")
    if not isinstance(sentence, str):
        raise GroundingError("invalid_sentence")
    spoken = sentence.strip()
    if not spoken or len(spoken) > 700 or len(spoken.split()) > 100:
        raise GroundingError("empty_or_oversized_speech")
    expected_url = facts.get("apply_url")
    for raw_url in _URL_RE.findall(spoken):
        if raw_url != expected_url and raw_url.rstrip(".,!?;:") != expected_url:
            raise GroundingError("unsupported_url")
    without_urls = _URL_RE.sub("", spoken)
    allowed_numbers = {
        number
        for key in _NUMERIC_FACTS
        for number in _NUMBER_RE.findall(_URL_RE.sub("", str(facts.get(key, ""))))
    }
    if set(_NUMBER_RE.findall(without_urls)) - allowed_numbers:
        raise GroundingError("unsupported_number")
    return Speech(spoken, stance)


class SentenceDecoder:
    def __init__(self):
        self.buffer = ""
        self.count = 0

    def push(self, chunk: str) -> list[dict]:
        self.buffer += chunk
        if len(self.buffer) > 4096:
            raise GroundingError("oversized_speech_envelope")
        result = []
        while self.buffer.strip():
            self.buffer = self.buffer.lstrip()
            try:
                payload, end = json.JSONDecoder().raw_decode(self.buffer)
            except json.JSONDecodeError:
                break
            self.count += 1
            if self.count > 1:
                raise GroundingError("too_many_speech_envelopes")
            result.append(payload)
            self.buffer = self.buffer[end:]
        return result

    def finish(self) -> None:
        if self.buffer.strip() or not self.count:
            raise GroundingError("incomplete_speech")


SPEECH_INSTRUCTIONS = """Write one natural spoken reply of one to three short sentences.
Output exactly one JSON object: {"sentence":"natural spoken prose","stance":"neutral|recommend|weak_option|poor_fit"}.
Use only CURRENT_FACTS and USER_PROFILE. Never invent or infer missing job details.
Any company, title, location, score or URL must match the supplied facts; use the exact apply_url.
Answer follow-ups directly without repeating the role identity or a stock closing question.
Choose a stance consistent with the verified score band, then stop and wait.
"""
