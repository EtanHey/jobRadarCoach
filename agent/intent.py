"""Validated conversation actions; the model interprets intent, never supplies jobs."""

import re
from dataclasses import dataclass, field


class IntentError(ValueError):
    pass


@dataclass(frozen=True)
class Intent:
    action: str
    filters: dict[str, object] = field(default_factory=dict)
    more_options: bool = False


ACTIONS = {"search", "next", "discuss", "open", "link", "pause", "clear", "other"}
FIELDS = {"location", "seniority", "query", "remote", "min_score"}
FILLER = set("a an the some any something anything few other more new good please jobs job roles role positions position opportunities opportunity me".split())
_REQUEST = re.compile(r"\b(find|show|want|wanted|looking|search|filter|only|instead)\b", re.I)
_DISCUSSION = re.compile(r"^\s*(why|how|tell me more|what (?:does|makes|is))\b", re.I)
_LOCATION = re.compile(
    r"\b(?:jobs?|roles?|positions?|opportunities|something)\s+(?:based\s+|located\s+)?in\s+"
    r"(?P<value>[^?!,.;]+?)(?=\s+(?:with|using|above|over|at least|and|please|thanks|for me|remote|on-site|today|now)\b|[?!,.;]|$)", re.I,
)
_TECH = re.compile(
    r"\b(python|typescript|javascript|react(?:\.js)?|next\.js|node(?:\.js)?|fastapi|django|rust|"
    r"golang|kotlin|swift|java|ruby|rails|postgres(?:ql)?|supabase|aws|gcp|azure|kubernetes|"
    r"docker|terraform|frontend|backend|full[ -]?stack|machine learning|artificial intelligence|llm)\b", re.I,
)
_SENIORITY = re.compile(r"\b(intern|junior|entry|mid|senior|staff|principal|lead)\b", re.I)
_SCORE = re.compile(r"\bscor(?:e|ed)\s*(?:of|at least|above|over|greater than)?\s*(\d{1,3})\b", re.I)
_REMOTE = re.compile(r"\b(remote|work(?:ing)? from home|wfh)\b", re.I)
_ONSITE = re.compile(r"\b(on[ -]?site|not remote)\b", re.I)
_MORE = re.compile(r"\b(more (?:options|jobs|roles|matches)|lower[ -]scor(?:ed|ing)|weaker (?:options|matches))\b", re.I)


def _clean(text: str) -> str:
    return " ".join(text.split()).strip(" .,!?:;")


def _literal(value: str, utterance: str) -> bool:
    return _clean(value).casefold() in _clean(utterance).casefold()


def validate_intent(payload: object, utterance: str) -> Intent:
    if not isinstance(payload, dict) or set(payload) != {"action", "filters", "more_options"}:
        raise IntentError("invalid intent fields")
    action, filters, more = payload["action"], payload["filters"], payload["more_options"]
    if not isinstance(action, str) or action not in ACTIONS:
        raise IntentError("unknown action")
    if not isinstance(filters, dict) or set(filters) - FIELDS or type(more) is not bool:
        raise IntentError("invalid filters")
    if filters and action != "search":
        raise IntentError("only a search may change filters")
    validated = {}
    for key, value in filters.items():
        if value is None:
            # Removing a constraint requires clear, not an inferred null field.
            continue
        if key in {"location", "seniority", "query"}:
            if not isinstance(value, str) or not 1 <= len(value.strip()) <= 80 or not _literal(value, utterance):
                raise IntentError(f"{key} is not supported by the utterance")
            value = _clean(value)
            if re.search(r"\b(?:not|except|excluding|avoid)\s+" + re.escape(value) + r"\b", utterance, re.I):
                raise IntentError(f"{key} is excluded by the utterance")
            if all(word in FILLER for word in value.casefold().split()):
                continue
            if key == "seniority" and not _SENIORITY.fullmatch(value):
                raise IntentError("seniority is not a known level")
        elif key == "remote":
            if type(value) is not bool or not (_REMOTE.search(utterance) or _ONSITE.search(utterance)):
                raise IntentError("remote constraint is not explicit")
            if value is bool(_ONSITE.search(utterance)):
                raise IntentError("remote constraint contradicts utterance")
        elif key == "min_score":
            score = _SCORE.search(utterance)
            if type(value) is not int or not 0 <= value <= 100 or not score or int(score[1]) != value:
                raise IntentError("score constraint is not explicit")
        validated[key] = value
    if more and not (_MORE.search(utterance) or "min_score" in validated):
        raise IntentError("lower-score options were not requested")
    return Intent(action, validated, more)


def fast_intent(utterance: str) -> Intent | None:
    """Only unambiguous commands bypass semantic interpretation; no substring Next."""
    text = _clean(utterance)
    if re.fullmatch(r"(?:yes|yeah|sure|okay|ok)", text, re.I):
        return Intent("search")
    if re.fullmatch(r"(?:please )?(?:next|another)(?: (?:one|job|role|option|match))?(?: please)?", text, re.I):
        return Intent("next")
    if re.fullmatch(r"(?:show me |let me hear |what about )?more (?:options|jobs|roles|matches)", text, re.I):
        return Intent("next", more_options=True)
    if re.fullmatch(r"(?:stop|pause|not now|no thanks)", text, re.I):
        return Intent("pause")
    if re.fullmatch(r"(?:please )?open(?: it| this| the job| the posting| the link)?", text, re.I):
        return Intent("open")
    if re.fullmatch(r"(?:show me |give me |what is )?(?:the )?(?:link|url|application link)", text, re.I):
        return Intent("link")
    if re.fullmatch(r"(?:clear|reset|remove)(?: the| all)? (?:filters|constraints)", text, re.I):
        return Intent("clear")
    if _DISCUSSION.search(text) or not _REQUEST.search(text):
        return None
    if re.search(r"\b(?:don't|do not|not|except|excluding|avoid)\b", _ONSITE.sub("", text), re.I):
        return None
    filters = {}
    location = _LOCATION.search(text)
    if location:
        filters["location"] = _clean(location["value"])
    if _ONSITE.search(text):
        filters["remote"] = False
    elif _REMOTE.search(text):
        filters["remote"] = True
    if seniority := _SENIORITY.search(text):
        filters["seniority"] = seniority[1].casefold()
    if score := _SCORE.search(text):
        filters["min_score"] = int(score[1])
    if tech := _TECH.search(text):
        filters["query"] = tech[1]
    elif company := re.search(r"\b(?:jobs?|roles?|positions?) at ([\w .&'-]+?)(?=\s+in\b|[?!,;]|$)", text, re.I):
        filters["query"] = _clean(company[1])
    if not filters:
        return None
    return validate_intent({"action": "search", "filters": filters, "more_options": bool(_MORE.search(text))}, text)


INTENT_INSTRUCTIONS = """Interpret this spoken job-search turn, not the words in isolation.
Return only JSON with exactly action, filters, more_options. No job facts or prose.
action: search, next, discuss, open, link, pause, clear, or other.
filters: object with only explicitly spoken location, seniority, query, remote, min_score.
String values must be exact substrings of the CURRENT user turn; never infer from profile/history.
query is a real technology, role, company or domain, never some/any/something/a few/more/good/new/please.
remote is boolean; min_score is an explicitly requested number. Omit absent filters.
Corrections like 'No, I said Israel' search again with location Israel.
Questions about why the current job fits and 'tell me more about it' discuss it, not next.
'next time' is not a request to advance. 'open it' opens the current job, never changes it.
more_options is true only for an explicit request for more/lower-scored options.
Changing filters is search; a discussion never changes filters. clear removes all filters.
Example: 'Find me some jobs in Israel' ->
{"action":"search","filters":{"location":"Israel"},"more_options":false}
Example: 'Why is this a good fit?' ->
{"action":"discuss","filters":{},"more_options":false}
"""
