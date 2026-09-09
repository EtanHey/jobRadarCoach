"""Render model-written framing around code-owned facts, one complete envelope at a time.

References and declared stance are deterministic checks. Free conversational prose
is not a semantic proof: adversarial model evaluation is a separate acceptance gate.
"""

import json
import re
from dataclasses import dataclass

from claim_audit import GroundingError


@dataclass(frozen=True)
class Speech:
    text: str
    stance: str
    references: tuple[str, ...]


def render_sentence(payload: object, facts: dict[str, str]) -> Speech:
    if not isinstance(payload, dict) or set(payload) != {"parts", "stance"}:
        raise GroundingError("invalid_speech_fields")
    parts, stance = payload["parts"], payload["stance"]
    if not isinstance(stance, str) or stance not in {"neutral", "recommend", "weak_option", "poor_fit"}:
        raise GroundingError("invalid_stance")
    score = facts.get("score")
    allowed = {"neutral"}
    if score is not None:
        allowed.add("recommend" if int(score) > 70 else "weak_option" if int(score) >= 40 else "poor_fit")
    if stance not in allowed:
        raise GroundingError("stance_contradicts_verified_score")
    if not isinstance(parts, list) or not 1 <= len(parts) <= 20:
        raise GroundingError("invalid_parts")
    output, references = [], []
    for part in parts:
        if not isinstance(part, dict):
            raise GroundingError("invalid_part")
        if set(part) == {"text"}:
            value = part["text"]
            if not isinstance(value, str):
                raise GroundingError("invalid_text")
            output.append(value)
        elif set(part) in ({"fact"}, {"fact", "quote"}):
            key = part["fact"]
            if not isinstance(key, str) or key not in facts or not facts[key]:
                raise GroundingError("unknown_fact")
            value = str(facts[key])
            if "quote" in part:
                quote = part["quote"]
                if not isinstance(quote, str) or not quote.strip() or quote not in value or key in {"score", "apply_url"}:
                    raise GroundingError("unsupported_fact_quote")
                value = quote
            references.append(key)
            output.append(value)
        else:
            raise GroundingError("invalid_part_fields")
    # Check concatenated raw text so splitting a URL/number between text parts
    # cannot circumvent the requirement to use a protected fact reference.
    framing = "".join(p["text"] for p in parts if "text" in p)
    if re.search(r"(?:https?://|www\.|\d)", framing, re.I):
        raise GroundingError("literal_url_or_number")
    spoken = "".join(output).strip()
    if not spoken or len(spoken) > 700 or len(spoken.split()) > 100:
        raise GroundingError("empty_or_oversized_speech")
    return Speech(spoken, stance, tuple(references))


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
            if self.count > 3:
                raise GroundingError("too_many_speech_envelopes")
            result.append(payload)
            self.buffer = self.buffer[end:]
        return result

    def finish(self) -> None:
        if self.buffer.strip() or not self.count:
            raise GroundingError("incomplete_speech")


SPEECH_INSTRUCTIONS = """Write natural spoken replies, one to three short sentences, then wait.
Output one JSON object per sentence with exactly parts and stance. No arrays/markdown around objects.
parts contains {"text":"your conversational wording"} and {"fact":"field"} entries.
For a shorter exact quote use {"fact":"reasons","quote":"Python"} if Python occurs in reasons.
Use fact parts for ALL factual claims, names, titles, locations, numbers, technologies and links.
Text parts are conversational framing, empathy, questions and your opinion, not new factual assertions.
Application code owns facts; you choose natural wording, emphasis and questions. No stock closing phrase.
Only use facts listed in CURRENT_FACTS. Never invent a posting, link, company or unsupported detail.
Never assert missing salary/funding/benefits/culture/hiring details. Say you do not have that information.
stance is neutral, recommend, weak_option or poor_fit and must match the verified score band.
No posting means neutral conversation/clarification only. Do not imply a job exists without supplied facts.
An initial offer identifies one role/company and why it may fit. A follow-up answers the actual question;
do not repeat the identity or a closing question every turn. STOP after this job and wait.
Above70 recommend;40–70 are weaker options only when asked; below40 plainly not worth pursuing.
Each object should be short enough to speak immediately. Do not put multiple long sentences in one object.
Example: {"parts":[{"text":"I'd look closer at "},{"fact":"title"},{"text":" with "},{"fact":"company"},{"text":"."}],"stance":"recommend"}
Example follow-up: {"parts":[{"text":"Absolutely. I see why that part bothers you."}],"stance":"neutral"}
"""
