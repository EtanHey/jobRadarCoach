"""Conservative, deterministic language-requirement guard over validated scores."""

import copy
import re


# Closed vocabulary: unknown technologies and unparsed clauses are not requirements.
_ALIASES = {
    "c#": "C#", "csharp": "C#", "c++": "C++", "java": "Java",
    "typescript": "TypeScript", "javascript": "JavaScript", "python": "Python",
    "kotlin": "Kotlin", "scala": "Scala", "rust": "Rust", "golang": "Go",
    "node.js": "Node.js", "nodejs": "Node.js", "react": "React",
}
_TECH = re.compile(r"(?<![\w+#])(?:" + "|".join(
    re.escape(name) for name in sorted(_ALIASES, key=len, reverse=True)
) + r")(?![\w+#])", re.I)
_OPTIONAL = re.compile(
    r"\b(?:nice[- ]to[- ]have|advantage|preferred|bonus|optional|a plus)\b", re.I
)
_NEGATED = re.compile(r"\b(?:no|not|without)\b", re.I)
_EXAMPLES = re.compile(r"\b(?:such as|for example|e\.g\.|like)\b", re.I)
_SECTIONS = {
    "required": {"requirements", "qualifications", "required qualifications",
                 "minimum qualifications", "what you'll bring", "what you’ll bring"},
    "optional": {"nice to have", "nice-to-have", "advantages", "preferred qualifications",
                 "bonus points", "bonus points for"},
    "work": {"responsibilities", "what you'll do", "what you’ll do"},
}
_SKILL = r"(?:experience|proficiency|knowledge|expertise|skills?)"
_SKILL_PREFIX = re.compile(
    rf"^(?:[\w+’'-]+\s+){{0,6}}{_SKILL}\s+(?:in|with|of)\s+(.+)$", re.I
)
_SKILL_SUFFIX = re.compile(rf"^(.+?)\s+{_SKILL}$", re.I)
_EXPLICIT = re.compile(r"^(.+?)\s+(?:is\s+)?(?:required|mandatory|a must)$", re.I)


def _clauses(expression):
    # Only complete closed-vocabulary lists; unknown operands or mixed AND/OR abstain.
    parts = re.split(r"\s*(,?\s+(?:and/or|or/and|and|or)\s+|,|/)\s*", expression, flags=re.I)
    operands = parts[::2]
    operators = [part.strip().lstrip(",").strip().casefold() for part in parts[1::2]]
    if not all(_TECH.fullmatch(part.strip()) for part in operands):
        return
    names = sorted({_ALIASES[part.strip().casefold()] for part in operands})
    alternative = any(op in {"or", "/", "and/or", "or/and"} for op in operators)
    if alternative and "and" in operators:
        return
    if alternative:
        yield tuple(names)
    else:
        yield from ((name,) for name in names)


def _requirements(jd):
    section = None
    for raw in jd.splitlines():
        line = raw.strip()
        if not line:
            continue
        label = line.strip("#*_ :–—-").casefold()
        matched = next((key for key, labels in _SECTIONS.items() if label in labels), None)
        if matched:
            section = matched
            continue
        # A new heading ends the previous section, including unknown headings.
        if line.startswith("#") or (line.startswith("**") and line.endswith("**")) or (
            not line.startswith(("-", "*", "•")) and len(line.split()) <= 6
            and not _TECH.search(line) and not re.search(r"[.!?;]", line)
        ):
            section = None
            continue
        if (section == "optional" or _OPTIONAL.search(line) or _EXAMPLES.search(line)
                or _NEGATED.search(line)):
            continue
        text = line.lstrip("-*• ").rstrip(". ")
        frame = _EXPLICIT.fullmatch(text)
        if frame is None and section == "required":
            frame = _SKILL_PREFIX.fullmatch(text) or _SKILL_SUFFIX.fullmatch(text)
        if frame is None and section == "work":
            frame = re.search(r"\busing\s+(.+)$", text, re.I)
        if frame:
            yield from _clauses(frame[1])


def _demonstrated(profile):
    names = set()
    for signal in profile.get("fit_signals", []):
        if signal.get("status") == "verified":
            names.update(_ALIASES[tag.casefold()] for tag in signal.get("tags", [])
                         if tag.casefold() in _ALIASES)
    # Preferences and fit_terms are intentionally excluded from skill evidence.
    for name, modes in profile.get("candidate", {}).get("professional_depth", {}).items():
        if name.casefold() in _ALIASES:
            canonical = _ALIASES[name.casefold()]
            if "hands-on" in modes:
                names.add(canonical)
            else:
                names.discard(canonical)
    return names


def apply_stack_gap_guard(annotation, posting, profile):
    """Hold actionable advice for unevidenced required stack; preserve human decisions."""
    jd = posting.get("jd_text") or posting.get("raw_jd") or ""
    demonstrated = _demonstrated(profile)
    gaps = sorted({" or ".join(clause) for clause in _requirements(jd)
                   if not demonstrated.intersection(clause)})
    if not gaps:
        return annotation
    result = copy.deepcopy(annotation)
    reason = next(r for r in result["reasons"] if r["factor"] == "stack_domain_evidence")
    note = ("Required stack not evidenced by verified skill tags/hands-on depth: "
            + "; ".join(gaps) + ". Confirm before pursuing.")
    if reason["detail"].startswith(note):
        return result
    reason["detail"] = note + " " + reason["detail"]
    if reason["assessment"] == "positive":
        reason["assessment"] = "mixed"
    # Explicit human verdicts remain authoritative; all other scores may only demote.
    human = posting.get("human_verdict", posting.get("verdict"))
    human = human.strip().lower() if isinstance(human, str) else None
    if human not in {"apply", "applied", "referral", "interesting", "skip", "not_relevant"}:
        if result["recommendation"] in {"apply", "referral"}:
            result["recommendation"] = "review"
    prefix = "Weak fit — " if result["fit_tier"] == "weak" else ""
    line = prefix + "Check required stack: " + "; ".join(gaps) + "."
    result["fit_line"] = line if len(line) <= 160 else prefix + "Check required stack; see stack evidence."
    return result
